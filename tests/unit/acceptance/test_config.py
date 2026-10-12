from pathlib import Path

import pytest
from pydantic import ValidationError

from hiyelx.acceptance import (
    AcceptanceConfigurationError,
    HardwareAcceptanceConfig,
    load_hardware_acceptance_config,
)


def _valid_document() -> dict[str, object]:
    return {
        "schema_version": "1",
        "driver_identity": "motor.dynamixel.xl430_w250_t",
        "expected_motor_model": "XL430-W250-T",
        "transport_identifier": "operator-supplied-transport",
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


def test_acceptance_config_is_strict_frozen_and_complete() -> None:
    config = HardwareAcceptanceConfig.model_validate(_valid_document(), strict=True)

    assert config.driver_identity == "motor.dynamixel.xl430_w250_t"
    assert config.command_bounds.minimum_rad_s == -0.3
    assert config.movement_authorized is False
    with pytest.raises(ValidationError):
        config.__setattr__("movement_authorized", True)


@pytest.mark.parametrize("missing", tuple(_valid_document()))
def test_missing_required_value_is_rejected(missing: str) -> None:
    document = _valid_document()
    del document[missing]

    with pytest.raises(ValidationError):
        HardwareAcceptanceConfig.model_validate(document, strict=True)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("driver_identity", ""),
        ("expected_motor_model", " "),
        ("transport_identifier", "\t"),
        ("evidence_session_id", "session/with/path"),
        ("device_id", -1),
        ("device_id", 1.0),
        ("baud_rate", 0),
        ("baud_rate", 57_600.0),
        ("operation_deadline_seconds", 0.0),
        ("operation_deadline_seconds", -1.0),
        ("operation_deadline_seconds", float("inf")),
        ("movement_authorized", 1),
    ],
)
def test_invalid_scalar_value_is_rejected(field: str, value: object) -> None:
    document = _valid_document()
    document[field] = value

    with pytest.raises(ValidationError):
        HardwareAcceptanceConfig.model_validate(document, strict=True)


@pytest.mark.parametrize(
    "bounds",
    [
        {"minimum_rad_s": 0.1, "maximum_rad_s": 0.2},
        {"minimum_rad_s": -0.2, "maximum_rad_s": -0.1},
        {"minimum_rad_s": 0.1, "maximum_rad_s": -0.1},
        {"minimum_rad_s": -0.1, "maximum_rad_s": -0.1},
        {"minimum_rad_s": float("nan"), "maximum_rad_s": 0.1},
        {"minimum_rad_s": -0.1, "maximum_rad_s": float("inf")},
    ],
)
def test_invalid_command_bounds_are_rejected(bounds: dict[str, float]) -> None:
    document = _valid_document()
    document["command_bounds"] = bounds

    with pytest.raises(ValidationError):
        HardwareAcceptanceConfig.model_validate(document, strict=True)


def test_unknown_fields_are_rejected() -> None:
    document = _valid_document()
    document["credential"] = "must-not-be-accepted"

    with pytest.raises(ValidationError):
        HardwareAcceptanceConfig.model_validate(document, strict=True)


def test_loader_errors_do_not_reveal_personal_path(tmp_path: Path) -> None:
    private_path = tmp_path / "private-device-config.yaml"
    private_path.write_text("schema_version: [", encoding="utf-8")

    with pytest.raises(AcceptanceConfigurationError) as caught:
        load_hardware_acceptance_config(private_path)

    assert str(private_path) not in str(caught.value)
    assert "private-device-config" not in str(caught.value)
