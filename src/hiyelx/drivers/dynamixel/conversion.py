"""XL430 register encoding and SI-unit conversion helpers.

Velocity commands use round-to-nearest with exact half values rounded away
from zero. Four-byte signed register values are transported as unsigned
two's-complement bit patterns.
"""

from math import floor, isfinite

from hiyelx.drivers.dynamixel.constants import (
    POSITION_UNIT_RADIANS,
    VELOCITY_UNIT_RADIANS_PER_SECOND,
    XL430_MAX_ABS_VELOCITY_RAW,
)

SIGNED_32_MIN = -(1 << 31)
SIGNED_32_MAX = (1 << 31) - 1
UNSIGNED_32_MAX = (1 << 32) - 1


class InvalidRawValueError(ValueError):
    """Raised when a raw value cannot fit the required 32-bit representation."""


class VelocityNotRepresentableError(ValueError):
    """Raised when a velocity exceeds the documented XL430 raw range."""

    def __init__(self, angular_velocity_radians_per_second: float) -> None:
        self.angular_velocity_radians_per_second = angular_velocity_radians_per_second
        super().__init__("velocity cannot be represented by the XL430 control table")


def decode_signed_32(raw_value: int) -> int:
    """Decode an unsigned four-byte register value as signed two's-complement."""
    if isinstance(raw_value, bool) or not 0 <= raw_value <= UNSIGNED_32_MAX:
        raise InvalidRawValueError("raw register value must be an unsigned 32-bit integer")
    if raw_value > SIGNED_32_MAX:
        return raw_value - (1 << 32)
    return raw_value


def encode_signed_32(value: int) -> int:
    """Encode a signed integer as an unsigned four-byte bit pattern."""
    if isinstance(value, bool) or not SIGNED_32_MIN <= value <= SIGNED_32_MAX:
        raise InvalidRawValueError("value must fit a signed 32-bit integer")
    return value & UNSIGNED_32_MAX


def radians_per_second_to_raw(angular_velocity_radians_per_second: float) -> int:
    """Convert rad/s to signed XL430 units using nearest, halves away from zero."""
    if not isfinite(angular_velocity_radians_per_second):
        raise VelocityNotRepresentableError(angular_velocity_radians_per_second)
    scaled = angular_velocity_radians_per_second / VELOCITY_UNIT_RADIANS_PER_SECOND
    magnitude = floor(abs(scaled) + 0.5)
    raw_value = magnitude if scaled >= 0.0 else -magnitude
    if abs(raw_value) > XL430_MAX_ABS_VELOCITY_RAW:
        raise VelocityNotRepresentableError(angular_velocity_radians_per_second)
    return raw_value


def raw_velocity_to_radians_per_second(raw_value: int) -> float:
    """Convert an unsigned four-byte Present Velocity value to rad/s."""
    return decode_signed_32(raw_value) * VELOCITY_UNIT_RADIANS_PER_SECOND


def raw_position_to_radians(raw_value: int) -> float:
    """Convert an unsigned four-byte Present Position value to radians."""
    return decode_signed_32(raw_value) * POSITION_UNIT_RADIANS
