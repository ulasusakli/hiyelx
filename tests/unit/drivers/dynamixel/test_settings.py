import pytest
from pydantic import ValidationError

from hiyelx.drivers.dynamixel.settings import XL430MotorSettings


def test_settings_defaults_match_reference_platform() -> None:
    settings = XL430MotorSettings(device="/dev/reference")

    assert settings.motor_id == 1
    assert settings.baud_rate == 57_600
    assert settings.max_abs_velocity_rad_s == 0.5


@pytest.mark.parametrize("device", ["", " ", "\t"])
def test_blank_device_is_rejected(device: str) -> None:
    with pytest.raises(ValidationError):
        XL430MotorSettings(device=device)


@pytest.mark.parametrize("motor_id", [-1, 253, 1.0, True])
def test_invalid_or_non_integer_motor_id_is_rejected(motor_id: object) -> None:
    with pytest.raises(ValidationError):
        XL430MotorSettings.model_validate(
            {"device": "/dev/reference", "motor_id": motor_id}, strict=True
        )


@pytest.mark.parametrize("baud_rate", [0, 38_400, 230_400, 57_600.0, True])
def test_unsupported_or_non_integer_baud_rate_is_rejected(baud_rate: object) -> None:
    with pytest.raises(ValidationError):
        XL430MotorSettings.model_validate(
            {"device": "/dev/reference", "baud_rate": baud_rate}, strict=True
        )


@pytest.mark.parametrize("limit", [0.0, -0.1, float("nan"), float("inf"), float("-inf")])
def test_invalid_velocity_limit_is_rejected(limit: float) -> None:
    with pytest.raises(ValidationError):
        XL430MotorSettings(device="/dev/reference", max_abs_velocity_rad_s=limit)


def test_unknown_setting_is_rejected() -> None:
    with pytest.raises(ValidationError):
        XL430MotorSettings.model_validate(
            {"device": "/dev/reference", "unexpected": True}, strict=True
        )
