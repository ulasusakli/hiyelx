from __future__ import annotations

import asyncio
from dataclasses import replace
from pathlib import Path

import pytest

from hiyelx.acceptance import (
    PHYSICAL_OPERATION_CONSENT,
    XL430_W250_T_ACCEPTANCE_PROFILE,
    AcceptanceCommandOutOfBoundsError,
    AcceptanceConfigurationError,
    AcceptanceEvidence,
    AcceptanceExecutionError,
    HardwareAcceptanceConfig,
    HardwareSelectionRequiredError,
    PhysicalConsentRequiredError,
    run_physical_acceptance,
    run_physical_acceptance_from_path,
)
from hiyelx.drivers.dynamixel import register_dynamixel_xl430_motor
from hiyelx.models import ModelRegistry


class FakeAcceptanceSession:
    def __init__(self, events: list[str], failure_stage: str | None = None) -> None:
        self.events = events
        self.failure_stage = failure_stage

    async def connect(self) -> None:
        self._perform("connect")

    async def identify(self) -> str:
        self._perform("identify")
        return "XL430-W250-T"

    async def apply_bounded_command(self, command_rad_s: float) -> None:
        self._perform(f"command:{command_rad_s:g}", failure_key="bounded_command")

    async def stop(self) -> None:
        self._perform("stop")

    async def disable_torque(self) -> None:
        self._perform("torque_disable")

    async def close(self) -> None:
        self._perform("close")

    def _perform(self, event: str, *, failure_key: str | None = None) -> None:
        self.events.append(event)
        key = failure_key or event
        if self.failure_stage == key:
            raise RuntimeError("credential=secret private-device-path arbitrary backend text")


class FakeSessionWithoutTorqueDisable:
    def __init__(self, events: list[str]) -> None:
        self.events = events

    async def connect(self) -> None:
        self.events.append("connect")

    async def identify(self) -> str:
        self.events.append("identify")
        return "XL430-W250-T"

    async def apply_bounded_command(self, command_rad_s: float) -> None:
        self.events.append(f"command:{command_rad_s:g}")

    async def stop(self) -> None:
        self.events.append("stop")

    async def close(self) -> None:
        self.events.append("close")


class SlowConnectSession(FakeAcceptanceSession):
    async def connect(self) -> None:
        self.events.append("connect")
        await asyncio.sleep(0.05)


def _config(
    *,
    movement_authorized: bool = True,
    operation_deadline_seconds: float = 2.0,
) -> HardwareAcceptanceConfig:
    return HardwareAcceptanceConfig.model_validate(
        {
            "schema_version": "1",
            "driver_identity": "motor.dynamixel.xl430_w250_t",
            "expected_motor_model": "XL430-W250-T",
            "transport_identifier": "private-device-credential-token",
            "device_id": 1,
            "baud_rate": 57_600,
            "command_bounds": {
                "minimum_rad_s": -0.3,
                "maximum_rad_s": 0.3,
            },
            "operation_deadline_seconds": operation_deadline_seconds,
            "movement_authorized": movement_authorized,
            "evidence_session_id": "hca-hw0-fake",
        },
        strict=True,
    )


def _registry() -> ModelRegistry:
    registry = ModelRegistry()
    register_dynamixel_xl430_motor(registry)
    return registry


@pytest.mark.asyncio
async def test_success_uses_defined_sequence_and_finalizes_after_close() -> None:
    events: list[str] = []
    finalized: list[AcceptanceEvidence] = []

    def finalize(result: AcceptanceEvidence) -> None:
        events.append("finalize")
        finalized.append(result)

    evidence = await run_physical_acceptance(
        _config(),
        _registry(),
        XL430_W250_T_ACCEPTANCE_PROFILE,
        lambda _config: FakeAcceptanceSession(events),
        command_rad_s=0.2,
        physical_operation_consent=PHYSICAL_OPERATION_CONSENT,
        pytest_hardware_selected=True,
        evidence_finalizer=finalize,
    )

    assert events == [
        "connect",
        "identify",
        "command:0.2",
        "stop",
        "torque_disable",
        "close",
        "finalize",
    ]
    assert evidence.outcome == "passed"
    assert evidence.attempted_steps == (
        "validate",
        "explicit_consent",
        "connect",
        "identify",
        "bounded_command",
        "stop",
        "torque_disable",
        "close",
        "evidence_finalization",
    )
    assert finalized == [evidence]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("failure_stage", "expected_events"),
    [
        ("connect", ["connect", "stop", "torque_disable", "close"]),
        ("identify", ["connect", "identify", "stop", "torque_disable", "close"]),
        (
            "bounded_command",
            ["connect", "identify", "command:0.2", "stop", "torque_disable", "close"],
        ),
        (
            "stop",
            ["connect", "identify", "command:0.2", "stop", "torque_disable", "close"],
        ),
    ],
)
async def test_cleanup_order_survives_relevant_failures(
    failure_stage: str, expected_events: list[str]
) -> None:
    events: list[str] = []

    with pytest.raises(AcceptanceExecutionError) as caught:
        await run_physical_acceptance(
            _config(),
            _registry(),
            XL430_W250_T_ACCEPTANCE_PROFILE,
            lambda _config: FakeAcceptanceSession(events, failure_stage),
            command_rad_s=0.2,
            physical_operation_consent=PHYSICAL_OPERATION_CONSENT,
            pytest_hardware_selected=True,
        )

    assert events == expected_events
    assert caught.value.evidence.attempted_steps[-3:] == (
        "torque_disable",
        "close",
        "evidence_finalization",
    )
    assert "credential" not in str(caught.value)
    assert "private-device" not in repr(caught.value.evidence)
    assert "arbitrary backend text" not in repr(caught.value.evidence)


@pytest.mark.asyncio
async def test_missing_consent_prevents_session_construction() -> None:
    constructions = 0

    def factory(_config: HardwareAcceptanceConfig) -> FakeAcceptanceSession:
        nonlocal constructions
        constructions += 1
        return FakeAcceptanceSession([])

    with pytest.raises(PhysicalConsentRequiredError):
        await run_physical_acceptance(
            _config(),
            _registry(),
            XL430_W250_T_ACCEPTANCE_PROFILE,
            factory,
            command_rad_s=0.2,
            physical_operation_consent=None,
            pytest_hardware_selected=True,
        )

    assert constructions == 0


@pytest.mark.asyncio
async def test_missing_pytest_selection_prevents_session_construction() -> None:
    constructions = 0

    def factory(_config: HardwareAcceptanceConfig) -> FakeAcceptanceSession:
        nonlocal constructions
        constructions += 1
        return FakeAcceptanceSession([])

    with pytest.raises(HardwareSelectionRequiredError):
        await run_physical_acceptance(
            _config(),
            _registry(),
            XL430_W250_T_ACCEPTANCE_PROFILE,
            factory,
            command_rad_s=0.2,
            physical_operation_consent=PHYSICAL_OPERATION_CONSENT,
            pytest_hardware_selected=False,
        )

    assert constructions == 0


@pytest.mark.asyncio
async def test_out_of_bounds_command_is_rejected_before_construction() -> None:
    constructions = 0

    def factory(_config: HardwareAcceptanceConfig) -> FakeAcceptanceSession:
        nonlocal constructions
        constructions += 1
        return FakeAcceptanceSession([])

    with pytest.raises(AcceptanceCommandOutOfBoundsError):
        await run_physical_acceptance(
            _config(),
            _registry(),
            XL430_W250_T_ACCEPTANCE_PROFILE,
            factory,
            command_rad_s=0.31,
            physical_operation_consent=PHYSICAL_OPERATION_CONSENT,
            pytest_hardware_selected=True,
        )

    assert constructions == 0


@pytest.mark.asyncio
async def test_invalid_document_fails_before_construction(tmp_path: Path) -> None:
    path = tmp_path / "acceptance.yaml"
    path.write_text("schema_version: '1'\nunexpected: true\n", encoding="utf-8")
    constructions = 0

    def factory(_config: HardwareAcceptanceConfig) -> FakeAcceptanceSession:
        nonlocal constructions
        constructions += 1
        return FakeAcceptanceSession([])

    with pytest.raises(AcceptanceConfigurationError):
        await run_physical_acceptance_from_path(
            path,
            _registry(),
            XL430_W250_T_ACCEPTANCE_PROFILE,
            factory,
            command_rad_s=0.2,
            physical_operation_consent=PHYSICAL_OPERATION_CONSENT,
            pytest_hardware_selected=True,
        )

    assert constructions == 0


@pytest.mark.asyncio
async def test_torque_disable_is_capability_dependent() -> None:
    events: list[str] = []

    evidence = await run_physical_acceptance(
        _config(),
        _registry(),
        replace(XL430_W250_T_ACCEPTANCE_PROFILE, supports_torque_disable=False),
        lambda _config: FakeSessionWithoutTorqueDisable(events),
        command_rad_s=-0.2,
        physical_operation_consent=PHYSICAL_OPERATION_CONSENT,
        pytest_hardware_selected=True,
    )

    assert events == ["connect", "identify", "command:-0.2", "stop", "close"]
    assert "torque_disable_unsupported" in evidence.attempted_steps


@pytest.mark.asyncio
async def test_missing_required_torque_disable_capability_fails_but_closes() -> None:
    events: list[str] = []

    with pytest.raises(AcceptanceExecutionError) as caught:
        await run_physical_acceptance(
            _config(),
            _registry(),
            XL430_W250_T_ACCEPTANCE_PROFILE,
            lambda _config: FakeSessionWithoutTorqueDisable(events),
            command_rad_s=0.2,
            physical_operation_consent=PHYSICAL_OPERATION_CONSENT,
            pytest_hardware_selected=True,
        )

    assert events == ["connect", "identify", "command:0.2", "stop", "close"]
    assert caught.value.stage == "torque_disable_missing"
    assert caught.value.evidence.attempted_steps[-3:] == (
        "torque_disable_missing",
        "close",
        "evidence_finalization",
    )


@pytest.mark.asyncio
async def test_operation_deadline_is_sanitized_and_cleanup_still_runs() -> None:
    events: list[str] = []

    with pytest.raises(AcceptanceExecutionError) as caught:
        await run_physical_acceptance(
            _config(operation_deadline_seconds=0.001),
            _registry(),
            XL430_W250_T_ACCEPTANCE_PROFILE,
            lambda _config: SlowConnectSession(events),
            command_rad_s=0.2,
            physical_operation_consent=PHYSICAL_OPERATION_CONSENT,
            pytest_hardware_selected=True,
        )

    assert caught.value.stage == "connect"
    assert events == ["connect", "stop", "torque_disable", "close"]
    assert "timeout" not in repr(caught.value.evidence)
