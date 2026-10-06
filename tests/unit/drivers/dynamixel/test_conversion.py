from math import isclose

import pytest

from hiyelx.drivers.dynamixel.constants import (
    POSITION_UNIT_RADIANS,
    VELOCITY_UNIT_RADIANS_PER_SECOND,
)
from hiyelx.drivers.dynamixel.conversion import (
    InvalidRawValueError,
    VelocityNotRepresentableError,
    decode_signed_32,
    encode_signed_32,
    radians_per_second_to_raw,
    raw_position_to_radians,
    raw_velocity_to_radians_per_second,
)


@pytest.mark.parametrize(
    ("signed", "encoded"),
    [(0, 0), (1, 1), (-1, 0xFFFFFFFF), (1023, 1023), (-1023, 0xFFFFFC01)],
)
def test_signed_32_two_complement_round_trip(signed: int, encoded: int) -> None:
    assert encode_signed_32(signed) == encoded
    assert decode_signed_32(encoded) == signed


@pytest.mark.parametrize("value", [-1, 1 << 32, True])
def test_decode_rejects_values_outside_unsigned_32_bits(value: int) -> None:
    with pytest.raises(InvalidRawValueError):
        decode_signed_32(value)


@pytest.mark.parametrize(
    ("multiplier", "expected"),
    [(0.0, 0), (1.0, 1), (-1.0, -1), (0.5, 1), (-0.5, -1), (1.49, 1), (1.5, 2)],
)
def test_velocity_rounding_is_nearest_with_halves_away_from_zero(
    multiplier: float,
    expected: int,
) -> None:
    assert radians_per_second_to_raw(multiplier * VELOCITY_UNIT_RADIANS_PER_SECOND) == expected


@pytest.mark.parametrize("raw", [0, 1, -1, 1023, -1023])
def test_velocity_conversion_preserves_signed_units(raw: int) -> None:
    encoded = encode_signed_32(raw)
    assert isclose(
        raw_velocity_to_radians_per_second(encoded),
        raw * VELOCITY_UNIT_RADIANS_PER_SECOND,
    )


@pytest.mark.parametrize("raw", [0, 1, -1, 4095, -4095])
def test_position_conversion_decodes_signed_units(raw: int) -> None:
    encoded = encode_signed_32(raw)
    assert isclose(raw_position_to_radians(encoded), raw * POSITION_UNIT_RADIANS)


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_velocity_conversion_rejects_non_finite_values(value: float) -> None:
    with pytest.raises(VelocityNotRepresentableError):
        radians_per_second_to_raw(value)


def test_velocity_conversion_rejects_value_outside_xl430_range() -> None:
    with pytest.raises(VelocityNotRepresentableError):
        radians_per_second_to_raw(1024 * VELOCITY_UNIT_RADIANS_PER_SECOND)
