"""Deterministic software-only compliance checks for external motor drivers."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from enum import Enum
from math import isfinite

from hiyelx.components import Motor, MotorCommand, MotorState
from hiyelx.models import (
    InvalidModelSettingsError,
    ModelCreationError,
)
from hiyelx.resources import LifecycleState, ResourceIdentity
from hiyelx.sdk.errors import DriverSdkError, InvalidMotorDriverResultError

type MotorFactory = Callable[[], Motor]
type MotorStateCheck = Callable[[MotorState], bool]
type ComplianceProbe = Callable[[], None]
type ComplianceEventSnapshot = Callable[[], tuple[str, ...]]


class MotorComplianceCheck(Enum):
    """Stable check names exposed by the software-only harness."""

    SOFTWARE_ONLY = "software_only"
    CONSTRUCTION = "construction"
    IDENTITY = "identity"
    INITIAL_LIFECYCLE = "initial_lifecycle"
    STRICT_SETTINGS = "strict_settings"
    NON_MOTOR_RESULT = "non_motor_result"
    STARTUP = "startup"
    INITIAL_STATE = "initial_state"
    COMMAND = "command"
    COMMAND_EFFECT = "command_effect"
    STOP = "stop"
    STOPPED_CONDITION = "stopped_condition"
    SHUTDOWN = "shutdown"
    CLEANUP_ORDER = "cleanup_order"


class MotorComplianceError(DriverSdkError):
    """Base class for sanitized motor compliance failures."""


class SoftwareOnlyComplianceRequiredError(MotorComplianceError):
    """Raised before fixture execution when software-only use is not declared."""

    def __init__(self) -> None:
        super().__init__("motor compliance requires an explicit software-only fixture")


class MotorComplianceFailure(MotorComplianceError):
    """Identify one failed check without exposing backend exception text."""

    def __init__(
        self,
        check: MotorComplianceCheck,
        *,
        events: tuple[str, ...] = (),
    ) -> None:
        self.check = check
        self.events = events
        super().__init__(f"motor compliance failed during {check.value}")


@dataclass(frozen=True, slots=True)
class MotorComplianceFixture:
    """Explicit callbacks and expectations for one fake or in-memory motor."""

    software_only: bool
    expected_identity: ResourceIdentity
    motor_factory: MotorFactory
    command: MotorCommand
    verify_command_effect: MotorStateCheck
    verify_stopped: MotorStateCheck
    reject_invalid_settings: ComplianceProbe
    reject_non_motor_builder: ComplianceProbe
    event_snapshot: ComplianceEventSnapshot
    expected_cleanup_order: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class MotorComplianceReport:
    """Immutable evidence returned after every required check passes."""

    identity: ResourceIdentity
    checks: tuple[MotorComplianceCheck, ...]
    initial_state: MotorState
    commanded_state: MotorState
    stopped_state: MotorState
    final_lifecycle: LifecycleState
    events: tuple[str, ...]


async def run_motor_compliance(
    fixture: MotorComplianceFixture,
) -> MotorComplianceReport:
    """Verify the bounded Motor contract using only a declared software fixture."""
    if not fixture.software_only:
        raise SoftwareOnlyComplianceRequiredError

    checks: list[MotorComplianceCheck] = [MotorComplianceCheck.SOFTWARE_ONLY]
    motor = _construct_motor(fixture)
    checks.append(MotorComplianceCheck.CONSTRUCTION)

    if motor.identity != fixture.expected_identity:
        raise _failure(fixture, MotorComplianceCheck.IDENTITY)
    checks.append(MotorComplianceCheck.IDENTITY)

    _require_lifecycle(
        fixture,
        motor,
        LifecycleState.CREATED,
        MotorComplianceCheck.INITIAL_LIFECYCLE,
    )
    checks.append(MotorComplianceCheck.INITIAL_LIFECYCLE)

    _require_creation_rejection(
        fixture,
        fixture.reject_invalid_settings,
        InvalidModelSettingsError,
        MotorComplianceCheck.STRICT_SETTINGS,
    )
    checks.append(MotorComplianceCheck.STRICT_SETTINGS)
    _require_creation_rejection(
        fixture,
        fixture.reject_non_motor_builder,
        InvalidMotorDriverResultError,
        MotorComplianceCheck.NON_MOTOR_RESULT,
    )
    checks.append(MotorComplianceCheck.NON_MOTOR_RESULT)

    await _run_step(fixture, MotorComplianceCheck.STARTUP, motor.start)
    _require_lifecycle(
        fixture,
        motor,
        LifecycleState.RUNNING,
        MotorComplianceCheck.STARTUP,
    )
    checks.append(MotorComplianceCheck.STARTUP)

    initial_state = await _read_state(
        fixture,
        motor,
        MotorComplianceCheck.INITIAL_STATE,
    )
    checks.append(MotorComplianceCheck.INITIAL_STATE)

    await _run_step(
        fixture,
        MotorComplianceCheck.COMMAND,
        lambda: motor.apply_command(fixture.command),
    )
    checks.append(MotorComplianceCheck.COMMAND)
    commanded_state = await _read_state(
        fixture,
        motor,
        MotorComplianceCheck.COMMAND_EFFECT,
    )
    if not _state_check(
        fixture,
        MotorComplianceCheck.COMMAND_EFFECT,
        fixture.verify_command_effect,
        commanded_state,
    ):
        raise _failure(fixture, MotorComplianceCheck.COMMAND_EFFECT)
    checks.append(MotorComplianceCheck.COMMAND_EFFECT)

    await _run_step(fixture, MotorComplianceCheck.STOP, motor.stop)
    checks.append(MotorComplianceCheck.STOP)
    stopped_state = await _read_state(
        fixture,
        motor,
        MotorComplianceCheck.STOPPED_CONDITION,
    )
    if not _state_check(
        fixture,
        MotorComplianceCheck.STOPPED_CONDITION,
        fixture.verify_stopped,
        stopped_state,
    ):
        raise _failure(fixture, MotorComplianceCheck.STOPPED_CONDITION)
    checks.append(MotorComplianceCheck.STOPPED_CONDITION)

    await _run_step(fixture, MotorComplianceCheck.SHUTDOWN, motor.shutdown)
    _require_lifecycle(
        fixture,
        motor,
        LifecycleState.STOPPED,
        MotorComplianceCheck.SHUTDOWN,
    )
    checks.append(MotorComplianceCheck.SHUTDOWN)

    events = _events(fixture, MotorComplianceCheck.CLEANUP_ORDER)
    expected = fixture.expected_cleanup_order
    if expected and events[-len(expected) :] != expected:
        raise MotorComplianceFailure(
            MotorComplianceCheck.CLEANUP_ORDER,
            events=events,
        )
    checks.append(MotorComplianceCheck.CLEANUP_ORDER)
    return MotorComplianceReport(
        identity=motor.identity,
        checks=tuple(checks),
        initial_state=initial_state,
        commanded_state=commanded_state,
        stopped_state=stopped_state,
        final_lifecycle=motor.state,
        events=events,
    )


def _construct_motor(fixture: MotorComplianceFixture) -> Motor:
    before = _events(fixture, MotorComplianceCheck.CONSTRUCTION)
    if before:
        raise MotorComplianceFailure(
            MotorComplianceCheck.CONSTRUCTION,
            events=before,
        )
    try:
        motor = fixture.motor_factory()
    except Exception as error:
        raise _failure(fixture, MotorComplianceCheck.CONSTRUCTION) from error
    after = _events(fixture, MotorComplianceCheck.CONSTRUCTION)
    if after:
        raise MotorComplianceFailure(
            MotorComplianceCheck.CONSTRUCTION,
            events=after,
        )
    return motor


def _require_creation_rejection(
    fixture: MotorComplianceFixture,
    probe: ComplianceProbe,
    expected_cause: type[Exception],
    check: MotorComplianceCheck,
) -> None:
    try:
        probe()
    except ModelCreationError as error:
        if isinstance(error.__cause__, expected_cause):
            return
        raise _failure(fixture, check) from error
    except Exception as error:
        raise _failure(fixture, check) from error
    raise _failure(fixture, check)


async def _run_step(
    fixture: MotorComplianceFixture,
    check: MotorComplianceCheck,
    operation: Callable[[], Awaitable[None]],
) -> None:
    try:
        await operation()
    except Exception as error:
        raise _failure(fixture, check) from error


async def _read_state(
    fixture: MotorComplianceFixture,
    motor: Motor,
    check: MotorComplianceCheck,
) -> MotorState:
    try:
        state = await motor.read_state()
    except Exception as error:
        raise _failure(fixture, check) from error
    if not (
        isfinite(state.angular_position_radians)
        and isfinite(state.angular_velocity_radians_per_second)
    ):
        raise _failure(fixture, check)
    return state


def _require_lifecycle(
    fixture: MotorComplianceFixture,
    motor: Motor,
    expected: LifecycleState,
    check: MotorComplianceCheck,
) -> None:
    if motor.state is not expected:
        raise _failure(fixture, check)


def _state_check(
    fixture: MotorComplianceFixture,
    check: MotorComplianceCheck,
    verifier: MotorStateCheck,
    state: MotorState,
) -> bool:
    try:
        return verifier(state)
    except Exception as error:
        raise _failure(fixture, check) from error


def _events(
    fixture: MotorComplianceFixture,
    check: MotorComplianceCheck,
) -> tuple[str, ...]:
    try:
        return tuple(fixture.event_snapshot())
    except Exception as error:
        raise MotorComplianceFailure(check) from error


def _failure(
    fixture: MotorComplianceFixture,
    check: MotorComplianceCheck,
) -> MotorComplianceFailure:
    try:
        events = tuple(fixture.event_snapshot())
    except Exception:
        events = ()
    return MotorComplianceFailure(check, events=events)
