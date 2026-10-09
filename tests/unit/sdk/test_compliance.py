from collections.abc import Callable
from typing import cast

import pytest
from pydantic import BaseModel, ConfigDict

from hiyelx.components import InvalidMotorStateError, Motor, MotorCommand, MotorState
from hiyelx.config import ResourceDefinition
from hiyelx.models import ModelRegistry
from hiyelx.resources import (
    LifecycleState,
    Resource,
    ResourceIdentity,
    ResourceShutdownError,
    ResourceStartupError,
)
from hiyelx.sdk import (
    MotorComplianceCheck,
    MotorComplianceFailure,
    MotorComplianceFixture,
    SoftwareOnlyComplianceRequiredError,
    register_motor_driver,
    run_motor_compliance,
)

MODEL_NAME = "motor.test.compliance"
IDENTITY = ResourceIdentity("compliance_motor")


class ComplianceSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    initial_position_radians: float


class FakeStartupError(Exception):
    pass


class FakeCommandError(Exception):
    pass


class FakeCleanupError(Exception):
    pass


class InMemoryMotor(Motor):
    def __init__(self, identity: ResourceIdentity) -> None:
        super().__init__(identity)
        self._motor_state = MotorState(1.25, 0.0)

    async def _apply_command(self, command: MotorCommand) -> None:
        self._motor_state = MotorState(
            self._motor_state.angular_position_radians,
            command.angular_velocity_radians_per_second,
        )

    async def _read_state(self) -> MotorState:
        return self._motor_state


class ComplianceMotor(Motor):
    def __init__(
        self,
        identity: ResourceIdentity,
        settings: ComplianceSettings,
        events: list[str],
        *,
        startup_failure: Exception | None = None,
        command_failure: Exception | None = None,
        shutdown_failure: Exception | None = None,
        non_finite_state: bool = False,
    ) -> None:
        super().__init__(identity)
        self._motor_state = MotorState(settings.initial_position_radians, 0.0)
        self._events = events
        self._startup_failure = startup_failure
        self._command_failure = command_failure
        self._shutdown_failure = shutdown_failure
        self._non_finite_state = non_finite_state

    async def _on_start(self) -> None:
        self._events.append("startup")
        if self._startup_failure is not None:
            raise self._startup_failure

    async def _on_shutdown(self) -> None:
        self._events.extend(("cleanup:zero", "cleanup:transport"))
        if self._shutdown_failure is not None:
            raise self._shutdown_failure

    async def _apply_command(self, command: MotorCommand) -> None:
        self._events.append(f"command:{command.angular_velocity_radians_per_second}")
        if self._command_failure is not None:
            raise self._command_failure
        self._motor_state = MotorState(
            self._motor_state.angular_position_radians,
            command.angular_velocity_radians_per_second,
        )

    async def _read_state(self) -> MotorState:
        if self._non_finite_state:
            return MotorState(float("nan"), 0.0)
        return self._motor_state


def _definition(settings: dict[str, object]) -> ResourceDefinition:
    return ResourceDefinition(
        identity=IDENTITY,
        model=MODEL_NAME,
        settings=settings,
    )


def _reject_invalid_settings() -> None:
    registry = ModelRegistry()
    register_motor_driver(
        registry,
        model_name=MODEL_NAME,
        settings_type=ComplianceSettings,
        builder=lambda identity, settings: ComplianceMotor(identity, settings, []),
    )
    registry.create(_definition({"initial_position_radians": "1.25"}))


def _reject_non_motor_builder() -> None:
    registry = ModelRegistry()

    def invalid_builder(
        identity: ResourceIdentity,
        settings: ComplianceSettings,
    ) -> Motor:
        del settings
        return cast(Motor, Resource(identity))

    register_motor_driver(
        registry,
        model_name=MODEL_NAME,
        settings_type=ComplianceSettings,
        builder=invalid_builder,
    )
    registry.create(_definition({"initial_position_radians": 1.25}))


def _fixture(
    events: list[str],
    *,
    software_only: bool = True,
    identity: ResourceIdentity = IDENTITY,
    startup_failure: Exception | None = None,
    command_failure: Exception | None = None,
    shutdown_failure: Exception | None = None,
    non_finite_state: bool = False,
    motor_factory: Callable[[], Motor] | None = None,
) -> MotorComplianceFixture:
    factory = motor_factory or (
        lambda: ComplianceMotor(
            identity,
            ComplianceSettings(initial_position_radians=1.25),
            events,
            startup_failure=startup_failure,
            command_failure=command_failure,
            shutdown_failure=shutdown_failure,
            non_finite_state=non_finite_state,
        )
    )
    return MotorComplianceFixture(
        software_only=software_only,
        expected_identity=IDENTITY,
        motor_factory=factory,
        command=MotorCommand(0.25),
        verify_command_effect=lambda state: (
            state.angular_velocity_radians_per_second == 0.25
        ),
        verify_stopped=lambda state: (
            state.angular_velocity_radians_per_second == 0.0
        ),
        reject_invalid_settings=_reject_invalid_settings,
        reject_non_motor_builder=_reject_non_motor_builder,
        event_snapshot=lambda: tuple(events),
        expected_cleanup_order=("cleanup:zero", "cleanup:transport"),
    )


@pytest.mark.asyncio
async def test_compliant_in_memory_fixture_passes() -> None:
    report = await run_motor_compliance(
        MotorComplianceFixture(
            software_only=True,
            expected_identity=IDENTITY,
            motor_factory=lambda: InMemoryMotor(IDENTITY),
            command=MotorCommand(0.25),
            verify_command_effect=lambda state: (
                state.angular_velocity_radians_per_second == 0.25
            ),
            verify_stopped=lambda state: (
                state.angular_velocity_radians_per_second == 0.0
            ),
            reject_invalid_settings=_reject_invalid_settings,
            reject_non_motor_builder=_reject_non_motor_builder,
            event_snapshot=lambda: (),
        )
    )

    assert report.identity == IDENTITY
    assert report.final_lifecycle is LifecycleState.STOPPED
    assert report.commanded_state.angular_velocity_radians_per_second == 0.25
    assert report.stopped_state.angular_velocity_radians_per_second == 0.0
    assert report.events == ()


@pytest.mark.asyncio
async def test_compliant_fake_backed_fixture_passes_with_ordered_events() -> None:
    events: list[str] = []

    report = await run_motor_compliance(_fixture(events))

    assert report.events == (
        "startup",
        "command:0.25",
        "command:0.0",
        "cleanup:zero",
        "cleanup:transport",
    )
    assert report.checks[-1] is MotorComplianceCheck.CLEANUP_ORDER


@pytest.mark.asyncio
async def test_non_software_fixture_is_rejected_before_construction() -> None:
    events: list[str] = []
    constructed = False

    def build() -> Motor:
        nonlocal constructed
        constructed = True
        return ComplianceMotor(
            IDENTITY,
            ComplianceSettings(initial_position_radians=0.0),
            events,
        )

    with pytest.raises(SoftwareOnlyComplianceRequiredError):
        await run_motor_compliance(
            _fixture(events, software_only=False, motor_factory=build)
        )

    assert not constructed
    assert events == []


@pytest.mark.asyncio
async def test_wrong_identity_is_rejected_before_startup() -> None:
    events: list[str] = []

    with pytest.raises(MotorComplianceFailure) as caught:
        await run_motor_compliance(
            _fixture(events, identity=ResourceIdentity("wrong_motor"))
        )

    assert caught.value.check is MotorComplianceCheck.IDENTITY
    assert events == []


@pytest.mark.asyncio
async def test_non_finite_state_preserves_motor_contract_failure() -> None:
    events: list[str] = []

    with pytest.raises(MotorComplianceFailure) as caught:
        await run_motor_compliance(_fixture(events, non_finite_state=True))

    assert caught.value.check is MotorComplianceCheck.INITIAL_STATE
    assert isinstance(caught.value.__cause__, InvalidMotorStateError)
    assert events == ["startup"]


@pytest.mark.asyncio
async def test_command_verification_failure_is_sanitized() -> None:
    events: list[str] = []
    fixture = _fixture(events)
    fixture = MotorComplianceFixture(
        software_only=fixture.software_only,
        expected_identity=fixture.expected_identity,
        motor_factory=fixture.motor_factory,
        command=fixture.command,
        verify_command_effect=lambda state: (_ for _ in ()).throw(
            RuntimeError("credential=top-secret /dev/private")
        ),
        verify_stopped=fixture.verify_stopped,
        reject_invalid_settings=fixture.reject_invalid_settings,
        reject_non_motor_builder=fixture.reject_non_motor_builder,
        event_snapshot=fixture.event_snapshot,
        expected_cleanup_order=fixture.expected_cleanup_order,
    )

    with pytest.raises(MotorComplianceFailure) as caught:
        await run_motor_compliance(fixture)

    assert caught.value.check is MotorComplianceCheck.COMMAND_EFFECT
    assert str(caught.value) == "motor compliance failed during command_effect"
    assert "top-secret" not in str(caught.value)
    assert "/dev/private" not in str(caught.value)


@pytest.mark.asyncio
async def test_startup_failure_preserves_cause_and_stops_sequence() -> None:
    events: list[str] = []
    primary = FakeStartupError("private startup detail")

    with pytest.raises(MotorComplianceFailure) as caught:
        await run_motor_compliance(_fixture(events, startup_failure=primary))

    assert caught.value.check is MotorComplianceCheck.STARTUP
    assert isinstance(caught.value.__cause__, ResourceStartupError)
    assert caught.value.__cause__.__cause__ is primary
    assert caught.value.events == ("startup",)
    assert events == ["startup"]


@pytest.mark.asyncio
async def test_command_failure_preserves_cause_and_stops_sequence() -> None:
    events: list[str] = []
    primary = FakeCommandError("private command detail")

    with pytest.raises(MotorComplianceFailure) as caught:
        await run_motor_compliance(_fixture(events, command_failure=primary))

    assert caught.value.check is MotorComplianceCheck.COMMAND
    assert caught.value.__cause__ is primary
    assert caught.value.events == ("startup", "command:0.25")
    assert events == ["startup", "command:0.25"]


@pytest.mark.asyncio
async def test_cleanup_failure_preserves_cause_and_ordered_events() -> None:
    events: list[str] = []
    primary = FakeCleanupError("private cleanup detail")

    with pytest.raises(MotorComplianceFailure) as caught:
        await run_motor_compliance(_fixture(events, shutdown_failure=primary))

    assert caught.value.check is MotorComplianceCheck.SHUTDOWN
    assert isinstance(caught.value.__cause__, ResourceShutdownError)
    assert caught.value.__cause__.__cause__ is primary
    assert caught.value.events[-2:] == ("cleanup:zero", "cleanup:transport")
