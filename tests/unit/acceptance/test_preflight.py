import pytest

from hiyelx.acceptance import (
    PHYSICAL_OPERATION_CONSENT,
    XL430_W250_T_ACCEPTANCE_PROFILE,
    AcceptanceConstraintError,
    AcceptanceModelMismatchError,
    HardwareAcceptanceConfig,
    PhysicalConsentRequiredError,
    preflight_hardware_acceptance,
)
from hiyelx.drivers.dynamixel import register_dynamixel_xl430_motor
from hiyelx.models import ModelRegistry
from tests.unit.drivers.dynamixel.fake_transport import FakeDynamixelTransport


def _config(**updates: object) -> HardwareAcceptanceConfig:
    document: dict[str, object] = {
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
        "operation_deadline_seconds": 2.0,
        "movement_authorized": False,
        "evidence_session_id": "hca-hw0-preflight",
    }
    document.update(updates)
    return HardwareAcceptanceConfig.model_validate(document, strict=True)


def test_preflight_resolves_driver_without_constructing_or_opening_transport() -> None:
    transports_created = 0

    def transport_factory(_settings: object) -> FakeDynamixelTransport:
        nonlocal transports_created
        transports_created += 1
        return FakeDynamixelTransport()

    registry = ModelRegistry()
    register_dynamixel_xl430_motor(registry, transport_factory=transport_factory)

    first = preflight_hardware_acceptance(
        _config(), registry, XL430_W250_T_ACCEPTANCE_PROFILE
    )
    second = preflight_hardware_acceptance(
        _config(), registry, XL430_W250_T_ACCEPTANCE_PROFILE
    )

    assert first == second
    assert transports_created == 0
    assert first.physical_operation_authorized is False
    output = "\n".join(first.evidence_lines())
    assert "private-device" not in output
    assert "credential" not in output
    assert "token" not in output
    assert "device-operations=none" in output


def test_movement_authorization_requires_exact_separate_consent() -> None:
    registry = ModelRegistry()
    register_dynamixel_xl430_motor(registry)
    config = _config(movement_authorized=True)

    with pytest.raises(PhysicalConsentRequiredError):
        preflight_hardware_acceptance(
            config,
            registry,
            XL430_W250_T_ACCEPTANCE_PROFILE,
            physical_operation_consent="yes",
        )

    plan = preflight_hardware_acceptance(
        config,
        registry,
        XL430_W250_T_ACCEPTANCE_PROFILE,
        physical_operation_consent=PHYSICAL_OPERATION_CONSENT,
    )
    assert plan.physical_operation_authorized is True


def test_model_mismatch_fails_before_any_driver_construction() -> None:
    transports_created = 0

    def transport_factory(_settings: object) -> FakeDynamixelTransport:
        nonlocal transports_created
        transports_created += 1
        return FakeDynamixelTransport()

    registry = ModelRegistry()
    register_dynamixel_xl430_motor(registry, transport_factory=transport_factory)

    with pytest.raises(AcceptanceModelMismatchError):
        preflight_hardware_acceptance(
            _config(expected_motor_model="Not-The-Expected-Motor"),
            registry,
            XL430_W250_T_ACCEPTANCE_PROFILE,
        )

    assert transports_created == 0


@pytest.mark.parametrize(
    "updates",
    [
        {"device_id": 253},
        {"baud_rate": 38_400},
        {
            "command_bounds": {
                "minimum_rad_s": -0.6,
                "maximum_rad_s": 0.3,
            }
        },
        {
            "command_bounds": {
                "minimum_rad_s": -0.3,
                "maximum_rad_s": 0.6,
            }
        },
    ],
)
def test_driver_specific_constraints_are_rejected(updates: dict[str, object]) -> None:
    registry = ModelRegistry()
    register_dynamixel_xl430_motor(registry)

    with pytest.raises(AcceptanceConstraintError):
        preflight_hardware_acceptance(
            _config(**updates), registry, XL430_W250_T_ACCEPTANCE_PROFILE
        )
