"""Explicit composition helper for the deterministic simulated motor model."""

from pydantic import BaseModel, ConfigDict, ValidationError

from hiyelx.config import ResourceDefinition
from hiyelx.models import InvalidModelSettingsError, ModelRegistry
from hiyelx.resources import Resource
from hiyelx.simulation.motor import SimulatedMotor

SIMULATED_MOTOR_MODEL = "motor.simulated"


class _SimulatedMotorSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


def register_simulated_motor(registry: ModelRegistry) -> None:
    """Explicitly register ``motor.simulated`` in the supplied registry."""
    registry.register(SIMULATED_MOTOR_MODEL, _create_simulated_motor)


def _create_simulated_motor(definition: ResourceDefinition) -> Resource:
    try:
        _SimulatedMotorSettings.model_validate(definition.settings, strict=True)
    except ValidationError as error:
        raise InvalidModelSettingsError(SIMULATED_MOTOR_MODEL) from error
    return SimulatedMotor(definition.identity)
