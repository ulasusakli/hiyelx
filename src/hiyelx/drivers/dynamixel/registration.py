"""Explicit registration for the fixed XL430-W250-T motor model."""

from collections.abc import Callable

from hiyelx.drivers.dynamixel.settings import XL430MotorSettings
from hiyelx.drivers.dynamixel.transport import (
    DynamixelTransport,
    SdkDynamixelTransport,
)
from hiyelx.drivers.dynamixel.xl430_motor import XL430Motor
from hiyelx.models import ModelRegistry
from hiyelx.resources import ResourceIdentity
from hiyelx.sdk import register_motor_driver

XL430_W250_T_MODEL = "motor.dynamixel.xl430_w250_t"
TransportFactory = Callable[[XL430MotorSettings], DynamixelTransport]


def register_dynamixel_xl430_motor(
    registry: ModelRegistry,
    *,
    transport_factory: TransportFactory | None = None,
) -> None:
    """Register the XL430 factory without opening or discovering hardware."""
    factory = transport_factory or _default_transport_factory

    def create(identity: ResourceIdentity, settings: XL430MotorSettings) -> XL430Motor:
        return XL430Motor(
            identity,
            settings,
            factory(settings),
        )

    register_motor_driver(
        registry,
        model_name=XL430_W250_T_MODEL,
        settings_type=XL430MotorSettings,
        builder=create,
    )


def _default_transport_factory(settings: XL430MotorSettings) -> DynamixelTransport:
    return SdkDynamixelTransport(settings.device)
