"""Driver-specific limits consumed by the generic acceptance preflight."""

from dataclasses import dataclass

from hiyelx.drivers.dynamixel.constants import SUPPORTED_BAUD_RATES
from hiyelx.drivers.dynamixel.registration import XL430_W250_T_MODEL


@dataclass(frozen=True, slots=True)
class AcceptanceDriverProfile:
    """Static compatibility metadata; constructing a profile performs no I/O."""

    driver_identity: str
    compatible_motor_models: frozenset[str]
    minimum_device_id: int
    maximum_device_id: int
    supported_baud_rates: frozenset[int]
    minimum_command_rad_s: float
    maximum_command_rad_s: float
    supports_torque_disable: bool


XL430_W250_T_ACCEPTANCE_PROFILE = AcceptanceDriverProfile(
    driver_identity=XL430_W250_T_MODEL,
    compatible_motor_models=frozenset({"XL430-W250-T"}),
    minimum_device_id=0,
    maximum_device_id=252,
    supported_baud_rates=frozenset(SUPPORTED_BAUD_RATES),
    minimum_command_rad_s=-0.5,
    maximum_command_rad_s=0.5,
    supports_torque_disable=True,
)
