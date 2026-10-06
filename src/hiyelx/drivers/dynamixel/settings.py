"""Strict settings for the fixed XL430-W250-T reference driver."""

from math import isfinite
from typing import Self

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from hiyelx.drivers.dynamixel.constants import SUPPORTED_BAUD_RATES


class XL430MotorSettings(BaseModel):
    """Validated one-motor/one-port settings; validation performs no I/O."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    device: str
    motor_id: int = 1
    baud_rate: int = 57_600
    max_abs_velocity_rad_s: float = 0.5

    @field_validator("device")
    @classmethod
    def _device_must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("device must not be blank")
        return value

    @field_validator("motor_id")
    @classmethod
    def _motor_id_must_be_valid(cls, value: int) -> int:
        if not 0 <= value <= 252:
            raise ValueError("motor_id must be from 0 through 252")
        return value

    @field_validator("baud_rate")
    @classmethod
    def _baud_rate_must_be_supported(cls, value: int) -> int:
        if value not in SUPPORTED_BAUD_RATES:
            raise ValueError("baud_rate is not supported by the XL430-W250-T")
        return value

    @model_validator(mode="after")
    def _velocity_limit_must_be_positive_and_finite(self) -> Self:
        value = self.max_abs_velocity_rad_s
        if not isfinite(value) or value <= 0.0:
            raise ValueError("max_abs_velocity_rad_s must be positive and finite")
        return self
