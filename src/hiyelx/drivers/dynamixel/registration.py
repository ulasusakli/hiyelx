"""Explicit registration for the fixed XL430-W250-T motor model."""

from collections.abc import Callable

from pydantic import ValidationError

from hiyelx.config import ResourceDefinition
from hiyelx.drivers.dynamixel.settings import XL430MotorSettings
from hiyelx.drivers.dynamixel.transport import (
    DynamixelTransport,
    SdkDynamixelTransport,
)
from hiyelx.drivers.dynamixel.xl430_motor import XL430Motor
from hiyelx.models import InvalidModelSettingsError, ModelRegistry
from hiyelx.resources import Resource

XL430_W250_T_MODEL = "motor.dynamixel.xl430_w250_t"
TransportFactory = Callable[[XL430MotorSettings], DynamixelTransport]


def register_dynamixel_xl430_motor(
    registry: ModelRegistry,
    *,
    transport_factory: TransportFactory | None = None,
) -> None:
    """Register the XL430 factory without opening or discovering hardware."""
    factory = transport_factory or _default_transport_factory

    def create(definition: ResourceDefinition) -> Resource:
        try:
            settings = XL430MotorSettings.model_validate(definition.settings, strict=True)
        except ValidationError as error:
            raise InvalidModelSettingsError(XL430_W250_T_MODEL) from error
        return XL430Motor(
            definition.identity,
            settings,
            factory(settings),
        )

    registry.register(XL430_W250_T_MODEL, create)


def _default_transport_factory(settings: XL430MotorSettings) -> DynamixelTransport:
    return SdkDynamixelTransport(settings.device)
