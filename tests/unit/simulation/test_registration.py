from pathlib import Path

import pytest

from hiyelx.components import MotorCommand, MotorState
from hiyelx.config import ResourceDefinition, load_config
from hiyelx.models import (
    DuplicateModelRegistrationError,
    InvalidModelSettingsError,
    ModelCreationError,
    ModelRegistry,
)
from hiyelx.resources import LifecycleState, ResourceIdentity
from hiyelx.simulation import (
    SIMULATED_MOTOR_MODEL,
    SimulatedMotor,
    register_simulated_motor,
)


def test_simulated_motor_registration_is_explicit() -> None:
    registry = ModelRegistry()

    assert registry.registered_model_names() == ()

    register_simulated_motor(registry)

    assert registry.registered_model_names() == (SIMULATED_MOTOR_MODEL,)
    with pytest.raises(DuplicateModelRegistrationError):
        register_simulated_motor(registry)


def test_creation_from_validated_yaml_remains_pre_start(tmp_path: Path) -> None:
    definition = _load_definition(tmp_path, settings="{}")
    registry = ModelRegistry()
    register_simulated_motor(registry)

    resource = registry.create(definition)

    assert isinstance(resource, SimulatedMotor)
    assert resource.identity == ResourceIdentity("left_motor")
    assert resource.state is LifecycleState.CREATED


def test_unknown_simulated_motor_settings_are_rejected(tmp_path: Path) -> None:
    definition = _load_definition(tmp_path, settings="{unexpected: true}")
    registry = ModelRegistry()
    register_simulated_motor(registry)

    with pytest.raises(ModelCreationError) as caught:
        registry.create(definition)

    assert isinstance(caught.value.__cause__, InvalidModelSettingsError)
    assert caught.value.__cause__.__cause__ is not None


@pytest.mark.asyncio
async def test_created_motor_uses_existing_deterministic_api(tmp_path: Path) -> None:
    definition = _load_definition(tmp_path, settings="{}")
    registry = ModelRegistry()
    register_simulated_motor(registry)
    resource = registry.create(definition)
    assert isinstance(resource, SimulatedMotor)

    await resource.start()
    await resource.apply_command(MotorCommand(2.0))
    resource.advance_time(1.5)

    assert await resource.read_state() == MotorState(3.0, 2.0)


def _load_definition(tmp_path: Path, settings: str) -> ResourceDefinition:
    source = f"""\
schema_version: "1"
resources:
  - identity: left_motor
    model: motor.simulated
    settings: {settings}
"""
    path = tmp_path / "runtime.yaml"
    path.write_text(source, encoding="utf-8")
    return load_config(path).resources[0]
