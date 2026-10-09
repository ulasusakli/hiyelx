from typing import cast

import pytest
from pydantic import BaseModel, ConfigDict

from hiyelx.components import Motor, MotorCommand, MotorState
from hiyelx.config import ResourceDefinition
from hiyelx.models import InvalidModelSettingsError, ModelCreationError, ModelRegistry
from hiyelx.resources import Resource, ResourceIdentity
from hiyelx.sdk import InvalidMotorDriverResultError, register_motor_driver

MODEL_NAME = "motor.example.external"


class ExampleSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    initial_position_radians: float


class ExampleMotor(Motor):
    def __init__(self, identity: ResourceIdentity, settings: ExampleSettings) -> None:
        super().__init__(identity)
        self._state = MotorState(settings.initial_position_radians, 0.0)

    async def _apply_command(self, command: MotorCommand) -> None:
        self._state = MotorState(
            self._state.angular_position_radians,
            command.angular_velocity_radians_per_second,
        )

    async def _read_state(self) -> MotorState:
        return self._state


def test_register_motor_driver_validates_settings_and_builds_motor() -> None:
    captured_settings: list[ExampleSettings] = []

    def build(identity: ResourceIdentity, settings: ExampleSettings) -> Motor:
        captured_settings.append(settings)
        return ExampleMotor(identity, settings)

    registry = ModelRegistry()
    register_motor_driver(
        registry,
        model_name=MODEL_NAME,
        settings_type=ExampleSettings,
        builder=build,
    )

    resource = registry.create(_definition({"initial_position_radians": 1.25}))

    assert isinstance(resource, ExampleMotor)
    assert resource.identity == ResourceIdentity("external_motor")
    assert captured_settings == [ExampleSettings(initial_position_radians=1.25)]


@pytest.mark.parametrize(
    "settings",
    [
        {},
        {"initial_position_radians": "1.25"},
        {"initial_position_radians": 1.25, "unknown": True},
    ],
)
def test_register_motor_driver_rejects_invalid_settings(
    settings: dict[str, object],
) -> None:
    registry = ModelRegistry()
    register_motor_driver(
        registry,
        model_name=MODEL_NAME,
        settings_type=ExampleSettings,
        builder=ExampleMotor,
    )

    with pytest.raises(ModelCreationError) as caught:
        registry.create(_definition(settings))

    assert isinstance(caught.value.__cause__, InvalidModelSettingsError)


def test_register_motor_driver_rejects_non_motor_builder_result() -> None:
    def invalid_builder(
        identity: ResourceIdentity,
        settings: ExampleSettings,
    ) -> Motor:
        del settings
        return cast(Motor, Resource(identity))

    registry = ModelRegistry()
    register_motor_driver(
        registry,
        model_name=MODEL_NAME,
        settings_type=ExampleSettings,
        builder=invalid_builder,
    )

    with pytest.raises(ModelCreationError) as caught:
        registry.create(_definition({"initial_position_radians": 1.25}))

    assert isinstance(caught.value.__cause__, InvalidMotorDriverResultError)


def _definition(settings: dict[str, object]) -> ResourceDefinition:
    return ResourceDefinition(
        identity=ResourceIdentity("external_motor"),
        model=MODEL_NAME,
        settings=settings,
    )
