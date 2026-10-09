"""Explicit registration helper for external motor drivers.

Applications remain responsible for importing trusted driver packages and
calling their registration functions. Configuration never imports Python code,
scans installed packages, or discovers entry points.
"""

from collections.abc import Callable
from typing import cast

from pydantic import BaseModel, ValidationError

from hiyelx.components import Motor
from hiyelx.config import ResourceDefinition
from hiyelx.models import InvalidModelSettingsError, ModelRegistry
from hiyelx.resources import Resource, ResourceIdentity
from hiyelx.sdk.errors import InvalidMotorDriverResultError

type MotorDriverBuilder[SettingsT: BaseModel] = Callable[
    [ResourceIdentity, SettingsT], Motor
]


def register_motor_driver[SettingsT: BaseModel](
    registry: ModelRegistry,
    *,
    model_name: str,
    settings_type: type[SettingsT],
    builder: MotorDriverBuilder[SettingsT],
) -> None:
    """Register one trusted motor builder with strict settings validation."""

    def create(definition: ResourceDefinition) -> Resource:
        try:
            settings = settings_type.model_validate(definition.settings, strict=True)
        except ValidationError as error:
            raise InvalidModelSettingsError(model_name) from error
        motor = cast(object, builder(definition.identity, settings))
        if not isinstance(motor, Motor):
            raise InvalidMotorDriverResultError(model_name, type(motor))
        return motor

    registry.register(model_name, create)
