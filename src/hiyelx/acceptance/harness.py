"""Deterministic preflight and fake-verifiable physical-session sequencing."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Protocol, runtime_checkable

from hiyelx.acceptance.config import (
    PHYSICAL_OPERATION_CONSENT,
    HardwareAcceptanceConfig,
    load_hardware_acceptance_config,
)
from hiyelx.acceptance.errors import (
    AcceptanceCommandOutOfBoundsError,
    AcceptanceConstraintError,
    AcceptanceDriverUnavailableError,
    AcceptanceExecutionError,
    AcceptanceModelMismatchError,
    HardwareSelectionRequiredError,
    MovementNotAuthorizedError,
    PhysicalConsentRequiredError,
)
from hiyelx.acceptance.profiles import AcceptanceDriverProfile
from hiyelx.models import ModelRegistry


@dataclass(frozen=True, slots=True)
class AcceptancePlan:
    """Sanitized deterministic plan safe for logs and evidence."""

    evidence_session_id: str
    driver_identity: str
    expected_motor_model: str
    transport_reference: str
    device_id: int
    baud_rate: int
    minimum_command_rad_s: float
    maximum_command_rad_s: float
    operation_deadline_seconds: float
    physical_operation_authorized: bool
    torque_disable_supported: bool

    def evidence_lines(self) -> tuple[str, ...]:
        """Return stable key-value output without the raw transport identifier."""
        return (
            "acceptance-preflight=valid",
            f"session={self.evidence_session_id}",
            f"driver={self.driver_identity}",
            f"expected-model={self.expected_motor_model}",
            f"transport-reference={self.transport_reference}",
            f"device-id={self.device_id}",
            f"baud-rate={self.baud_rate}",
            f"command-min-rad-s={self.minimum_command_rad_s:g}",
            f"command-max-rad-s={self.maximum_command_rad_s:g}",
            f"operation-deadline-seconds={self.operation_deadline_seconds:g}",
            "physical-operation-authorized="
            f"{str(self.physical_operation_authorized).lower()}",
            f"torque-disable-supported={str(self.torque_disable_supported).lower()}",
            "device-operations=none",
        )


class AcceptanceSession(Protocol):
    """Injected physical collaborator; unit tests use deterministic fakes only."""

    async def connect(self) -> None: ...

    async def identify(self) -> str: ...

    async def apply_bounded_command(self, command_rad_s: float) -> None: ...

    async def stop(self) -> None: ...

    async def close(self) -> None: ...


@runtime_checkable
class TorqueDisableCapable(Protocol):
    """Optional capability for sessions that can explicitly disable torque."""

    async def disable_torque(self) -> None: ...


@dataclass(frozen=True, slots=True)
class AcceptanceEvidence:
    """Sanitized ordered result emitted after cleanup."""

    plan: AcceptancePlan
    outcome: str
    attempted_steps: tuple[str, ...]
    failure_stages: tuple[str, ...]


AcceptanceSessionFactory = Callable[[HardwareAcceptanceConfig], AcceptanceSession]
EvidenceFinalizer = Callable[[AcceptanceEvidence], None]


def preflight_hardware_acceptance(
    config: HardwareAcceptanceConfig,
    registry: ModelRegistry,
    profile: AcceptanceDriverProfile,
    *,
    physical_operation_consent: str | None = None,
) -> AcceptancePlan:
    """Resolve compatibility and return a sanitized plan without construction."""
    if config.driver_identity != profile.driver_identity:
        raise AcceptanceDriverUnavailableError
    try:
        registry.resolve(config.driver_identity)
    except Exception:
        raise AcceptanceDriverUnavailableError from None
    if config.expected_motor_model not in profile.compatible_motor_models:
        raise AcceptanceModelMismatchError
    if not profile.minimum_device_id <= config.device_id <= profile.maximum_device_id:
        raise AcceptanceConstraintError
    if config.baud_rate not in profile.supported_baud_rates:
        raise AcceptanceConstraintError
    bounds = config.command_bounds
    if (
        bounds.minimum_rad_s < profile.minimum_command_rad_s
        or bounds.maximum_rad_s > profile.maximum_command_rad_s
    ):
        raise AcceptanceConstraintError
    consented = physical_operation_consent == PHYSICAL_OPERATION_CONSENT
    if config.movement_authorized and not consented:
        raise PhysicalConsentRequiredError
    transport_digest = sha256(config.transport_identifier.encode("utf-8")).hexdigest()[:16]
    return AcceptancePlan(
        evidence_session_id=config.evidence_session_id,
        driver_identity=config.driver_identity,
        expected_motor_model=config.expected_motor_model,
        transport_reference=f"sha256:{transport_digest}",
        device_id=config.device_id,
        baud_rate=config.baud_rate,
        minimum_command_rad_s=bounds.minimum_rad_s,
        maximum_command_rad_s=bounds.maximum_rad_s,
        operation_deadline_seconds=config.operation_deadline_seconds,
        physical_operation_authorized=config.movement_authorized and consented,
        torque_disable_supported=profile.supports_torque_disable,
    )


async def run_physical_acceptance_from_path(
    path: str | Path,
    registry: ModelRegistry,
    profile: AcceptanceDriverProfile,
    session_factory: AcceptanceSessionFactory,
    *,
    command_rad_s: float,
    physical_operation_consent: str | None,
    pytest_hardware_selected: bool,
    evidence_finalizer: EvidenceFinalizer | None = None,
) -> AcceptanceEvidence:
    """Load before constructing a session, then execute the bounded sequence."""
    config = load_hardware_acceptance_config(path)
    return await run_physical_acceptance(
        config,
        registry,
        profile,
        session_factory,
        command_rad_s=command_rad_s,
        physical_operation_consent=physical_operation_consent,
        pytest_hardware_selected=pytest_hardware_selected,
        evidence_finalizer=evidence_finalizer,
    )


async def run_physical_acceptance(
    config: HardwareAcceptanceConfig,
    registry: ModelRegistry,
    profile: AcceptanceDriverProfile,
    session_factory: AcceptanceSessionFactory,
    *,
    command_rad_s: float,
    physical_operation_consent: str | None,
    pytest_hardware_selected: bool,
    evidence_finalizer: EvidenceFinalizer | None = None,
) -> AcceptanceEvidence:
    """Execute validate -> consent -> connect -> identify -> command -> cleanup."""
    plan = preflight_hardware_acceptance(
        config,
        registry,
        profile,
        physical_operation_consent=physical_operation_consent,
    )
    if not pytest_hardware_selected:
        raise HardwareSelectionRequiredError
    if not plan.physical_operation_authorized:
        raise MovementNotAuthorizedError
    if not plan.minimum_command_rad_s <= command_rad_s <= plan.maximum_command_rad_s:
        raise AcceptanceCommandOutOfBoundsError

    steps = ["validate", "explicit_consent"]
    failure_stages: list[str] = []
    try:
        session = session_factory(config)
    except Exception:
        evidence = _finalize_evidence(
            plan,
            steps,
            ["session_construction"],
            evidence_finalizer,
        )
        raise AcceptanceExecutionError("session_construction", evidence) from None

    primary_stage: str | None = None
    try:
        steps.append("connect")
        try:
            await _with_deadline(session.connect(), config.operation_deadline_seconds)
        except Exception:
            primary_stage = "connect"

        if primary_stage is None:
            steps.append("identify")
            try:
                identified_model = await _with_deadline(
                    session.identify(), config.operation_deadline_seconds
                )
                if identified_model != config.expected_motor_model:
                    raise AcceptanceModelMismatchError
            except Exception:
                primary_stage = "identify"

        if primary_stage is None:
            steps.append("bounded_command")
            try:
                await _with_deadline(
                    session.apply_bounded_command(command_rad_s),
                    config.operation_deadline_seconds,
                )
            except Exception:
                primary_stage = "bounded_command"
    finally:
        steps.append("stop")
        try:
            await _with_deadline(session.stop(), config.operation_deadline_seconds)
        except Exception:
            failure_stages.append("stop")

        if plan.torque_disable_supported and isinstance(session, TorqueDisableCapable):
            steps.append("torque_disable")
            try:
                await _with_deadline(
                    session.disable_torque(), config.operation_deadline_seconds
                )
            except Exception:
                failure_stages.append("torque_disable")
        elif plan.torque_disable_supported:
            steps.append("torque_disable_missing")
            failure_stages.append("torque_disable_missing")
        else:
            steps.append("torque_disable_unsupported")

        steps.append("close")
        try:
            await _with_deadline(session.close(), config.operation_deadline_seconds)
        except Exception:
            failure_stages.append("close")

    if primary_stage is not None:
        failure_stages.insert(0, primary_stage)
    evidence = _finalize_evidence(plan, steps, failure_stages, evidence_finalizer)
    if failure_stages:
        raise AcceptanceExecutionError(failure_stages[0], evidence) from None
    return evidence


async def _with_deadline[ResultT](
    operation: Awaitable[ResultT], timeout_seconds: float
) -> ResultT:
    async with asyncio.timeout(timeout_seconds):
        return await operation


def _finalize_evidence(
    plan: AcceptancePlan,
    steps: list[str],
    failure_stages: list[str],
    finalizer: EvidenceFinalizer | None,
) -> AcceptanceEvidence:
    steps.append("evidence_finalization")
    evidence = AcceptanceEvidence(
        plan=plan,
        outcome="failed" if failure_stages else "passed",
        attempted_steps=tuple(steps),
        failure_stages=tuple(failure_stages),
    )
    if finalizer is not None:
        try:
            finalizer(evidence)
        except Exception:
            failed_evidence = AcceptanceEvidence(
                plan=plan,
                outcome="failed",
                attempted_steps=tuple(steps),
                failure_stages=(*failure_stages, "evidence_finalization"),
            )
            raise AcceptanceExecutionError(
                "evidence_finalization", failed_evidence
            ) from None
    return evidence
