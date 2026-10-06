from pathlib import Path
from typing import cast

import pytest

from hiyelx.components import MotorCommand, MotorState
from hiyelx.config import ResourceDefinition, RuntimeConfig, load_config
from hiyelx.models import ModelCreationError, ModelRegistry
from hiyelx.resources import LifecycleState, Resource, ResourceIdentity
from hiyelx.runtime import (
    RuntimeConstructionError,
    RuntimeManager,
    RuntimeManagerState,
    UnknownOwnedResourceError,
)
from hiyelx.simulation import SimulatedMotor, register_simulated_motor


class RecordingResource(Resource):
    def __init__(self, identity: ResourceIdentity, events: list[str]) -> None:
        super().__init__(identity)
        self._events = events

    async def _on_start(self) -> None:
        self._events.append(f"start:{self.identity!s}")

    async def _on_shutdown(self) -> None:
        self._events.append(f"shutdown:{self.identity!s}")


def test_initial_state_plan_and_owned_instances() -> None:
    events: list[str] = []
    instances: dict[ResourceIdentity, Resource] = {}
    manager = RuntimeManager(_config(), _recording_registry(events, instances))

    assert manager.state is RuntimeManagerState.NEW
    assert manager.startup_plan == tuple(map(ResourceIdentity, ("motor", "controller")))
    assert manager.successful_start_order == ()
    assert tuple(manager.owned_resources) == manager.startup_plan
    assert len({id(resource) for resource in manager.owned_resources.values()}) == 2


@pytest.mark.asyncio
async def test_all_resources_are_created_before_startup_begins() -> None:
    events: list[str] = []
    manager = RuntimeManager(_config(), _recording_registry(events, {}))

    assert events == ["create:motor", "create:controller"]

    await manager.start()

    assert events == [
        "create:motor",
        "create:controller",
        "start:motor",
        "start:controller",
    ]


def test_lookup_and_snapshot_are_safe() -> None:
    instances: dict[ResourceIdentity, Resource] = {}
    manager = RuntimeManager(_config(), _recording_registry([], instances))
    motor_identity = ResourceIdentity("motor")

    assert manager.get_resource(motor_identity) is instances[motor_identity]
    with pytest.raises(UnknownOwnedResourceError):
        manager.get_resource(ResourceIdentity("missing"))

    snapshot = manager.owned_resources
    mutable_view = cast(dict[ResourceIdentity, Resource], snapshot)
    with pytest.raises(TypeError):
        mutable_view[ResourceIdentity("injected")] = Resource(ResourceIdentity("injected"))
    assert ResourceIdentity("injected") not in manager.owned_resources


def test_separate_managers_do_not_share_resources_or_state() -> None:
    first = RuntimeManager(_config(), _recording_registry([], {}))
    second = RuntimeManager(_config(), _recording_registry([], {}))

    assert first is not second
    assert first.get_resource(ResourceIdentity("motor")) is not second.get_resource(
        ResourceIdentity("motor")
    )
    assert first.state is second.state is RuntimeManagerState.NEW


def test_construction_failure_preserves_registry_error_chain() -> None:
    failure = ValueError("factory failure")

    def factory(definition: ResourceDefinition) -> Resource:
        raise failure

    registry = ModelRegistry()
    registry.register("test.resource", factory)

    with pytest.raises(RuntimeConstructionError) as caught:
        RuntimeManager(_config(), registry)

    assert caught.value.identity == ResourceIdentity("motor")
    assert isinstance(caught.value.__cause__, ModelCreationError)
    assert caught.value.__cause__.__cause__ is failure


@pytest.mark.asyncio
async def test_successful_lifecycle_uses_plan_and_reverse_shutdown_order() -> None:
    events: list[str] = []
    instances: dict[ResourceIdentity, Resource] = {}
    manager = RuntimeManager(_config(), _recording_registry(events, instances))

    await manager.start()

    assert manager.state is RuntimeManagerState.RUNNING
    assert manager.successful_start_order == manager.startup_plan
    assert all(resource.state is LifecycleState.RUNNING for resource in instances.values())

    await manager.shutdown()

    assert events[-2:] == ["shutdown:controller", "shutdown:motor"]
    assert manager.state is RuntimeManagerState.STOPPED
    assert all(resource.state is LifecycleState.STOPPED for resource in instances.values())


@pytest.mark.asyncio
async def test_real_config_registry_and_simulated_motor_lifecycle(tmp_path: Path) -> None:
    path = tmp_path / "runtime.yaml"
    path.write_text(
        """\
schema_version: "1"
resources:
  - identity: motor
    model: motor.simulated
    settings: {}
""",
        encoding="utf-8",
    )
    registry = ModelRegistry()
    register_simulated_motor(registry)
    manager = RuntimeManager(load_config(path), registry)
    resource = manager.get_resource(ResourceIdentity("motor"))
    assert isinstance(resource, SimulatedMotor)
    assert resource.state is LifecycleState.CREATED

    await manager.start()
    await resource.apply_command(MotorCommand(2.0))
    resource.advance_time(1.5)
    assert await resource.read_state() == MotorState(3.0, 2.0)

    await manager.shutdown()
    assert await resource.read_state() == MotorState(3.0, 0.0)


def _config() -> RuntimeConfig:
    return RuntimeConfig(
        schema_version="1",
        resources=[
            ResourceDefinition(
                identity=ResourceIdentity("controller"),
                model="test.resource",
                settings={},
                depends_on=(ResourceIdentity("motor"),),
            ),
            ResourceDefinition(
                identity=ResourceIdentity("motor"),
                model="test.resource",
                settings={},
            ),
        ],
    )


def _recording_registry(
    events: list[str],
    instances: dict[ResourceIdentity, Resource],
) -> ModelRegistry:
    def factory(definition: ResourceDefinition) -> Resource:
        events.append(f"create:{definition.identity!s}")
        resource = RecordingResource(definition.identity, events)
        instances[definition.identity] = resource
        return resource

    registry = ModelRegistry()
    registry.register("test.resource", factory)
    return registry
