from dataclasses import FrozenInstanceError

import pytest

from hiyelx.components import Motor, MotorCommand, MotorState
from hiyelx.config import ResourceDefinition, RuntimeConfig
from hiyelx.models import ModelRegistry
from hiyelx.resources import (
    BackendUnavailableError,
    HealthStatus,
    LifecycleState,
    Resource,
    ResourceHealth,
    ResourceIdentity,
)
from hiyelx.runtime import (
    RuntimeEventOperation,
    RuntimeEventOutcome,
    RuntimeManagerState,
    RuntimeOperations,
    RuntimeSafeStopError,
    RuntimeShutdownError,
    RuntimeStartupError,
)


class ControlledResource(Resource):
    def __init__(
        self,
        identity: ResourceIdentity,
        calls: list[str],
        *,
        fail_start: bool = False,
        fail_shutdown: bool = False,
        health_detail: str | None = None,
    ) -> None:
        super().__init__(identity)
        self._calls = calls
        self._fail_start = fail_start
        self._fail_shutdown = fail_shutdown
        self._health_detail = health_detail

    async def _on_start(self) -> None:
        self._calls.append(f"start:{self.identity!s}")
        if self._fail_start:
            raise BackendUnavailableError(
                "device=/dev/private credential=top-secret startup detail"
            )
        if self._health_detail is not None:
            self._set_health(ResourceHealth(HealthStatus.DEGRADED, self._health_detail))

    async def _on_shutdown(self) -> None:
        self._calls.append(f"shutdown:{self.identity!s}")
        if self._fail_shutdown:
            raise BackendUnavailableError(
                "device=/dev/private credential=top-secret shutdown detail"
            )


class ControlledMotor(Motor):
    def __init__(
        self,
        identity: ResourceIdentity,
        calls: list[str],
        *,
        fail_stop: bool,
    ) -> None:
        super().__init__(identity)
        self._calls = calls
        self._fail_stop = fail_stop

    async def _on_start(self) -> None:
        self._calls.append(f"start:{self.identity!s}")

    async def _on_shutdown(self) -> None:
        self._calls.append(f"shutdown:{self.identity!s}")

    async def _apply_command(self, command: MotorCommand) -> None:
        assert command == MotorCommand.zero_velocity()
        self._calls.append(f"safe-stop:{self.identity!s}")
        if self._fail_stop:
            raise RuntimeError("device=/dev/private credential=top-secret motor detail")

    async def _read_state(self) -> MotorState:
        return MotorState(0.0, 0.0)


def test_snapshot_before_startup_is_immutable_equal_and_observation_only() -> None:
    operations, resources, creations, calls = _resource_operations()
    assert creations == ["a", "b", "c"]
    before_calls = tuple(calls)

    first = operations.snapshot()
    second = operations.snapshot()

    assert first == second
    assert first.manager_state is RuntimeManagerState.NEW
    assert tuple(resource.identity.value for resource in first.resources) == ("a", "b", "c")
    assert first.startup_plan == tuple(map(ResourceIdentity, ("a", "b", "c")))
    assert first.successful_start_order == ()
    assert first.active_resource_order == ()
    assert first.event_high_water_mark is None
    assert first.events == ()
    assert tuple(calls) == before_calls
    assert creations == ["a", "b", "c"]
    assert all(resource.state is LifecycleState.CREATED for resource in resources.values())

    with pytest.raises(FrozenInstanceError):
        first.manager_state = RuntimeManagerState.RUNNING  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        first.resources[0].health_summary = "changed"  # type: ignore[misc]

    assert all(not isinstance(resource, Resource) for resource in first.resources)
    assert all(not isinstance(event, Resource) for event in first.events)


@pytest.mark.asyncio
async def test_snapshot_while_running_has_ordered_state_health_and_events() -> None:
    unsafe = "backend says /dev/private credential=top-secret"
    operations, _, _, calls = _resource_operations(health_details={"b": unsafe})

    await operations.start()
    before_snapshot = tuple(calls)
    snapshot = operations.snapshot()

    assert snapshot.manager_state is RuntimeManagerState.RUNNING
    assert snapshot.successful_start_order == snapshot.startup_plan
    assert snapshot.active_resource_order == snapshot.startup_plan
    assert tuple(resource.lifecycle_state for resource in snapshot.resources) == (
        LifecycleState.RUNNING,
        LifecycleState.RUNNING,
        LifecycleState.RUNNING,
    )
    assert tuple(resource.health_status for resource in snapshot.resources) == (
        HealthStatus.HEALTHY,
        HealthStatus.DEGRADED,
        HealthStatus.HEALTHY,
    )
    assert tuple(resource.health_summary for resource in snapshot.resources) == (
        None,
        None,
        None,
    )
    assert tuple(event.sequence for event in snapshot.events) == tuple(range(8))
    assert tuple(event.operation for event in snapshot.events) == (
        RuntimeEventOperation.RUNTIME_START,
        RuntimeEventOperation.RESOURCE_START,
        RuntimeEventOperation.RESOURCE_START,
        RuntimeEventOperation.RESOURCE_START,
        RuntimeEventOperation.RESOURCE_START,
        RuntimeEventOperation.RESOURCE_START,
        RuntimeEventOperation.RESOURCE_START,
        RuntimeEventOperation.RUNTIME_RUNNING,
    )
    assert snapshot.event_high_water_mark == 7
    assert tuple(calls) == before_snapshot
    assert unsafe not in repr(snapshot)


@pytest.mark.asyncio
async def test_snapshot_after_successful_shutdown_is_complete_and_ordered() -> None:
    operations, _, _, calls = _resource_operations()
    await operations.start()
    await operations.shutdown()

    snapshot = operations.snapshot()

    assert calls[-3:] == ["shutdown:c", "shutdown:b", "shutdown:a"]
    assert snapshot.manager_state is RuntimeManagerState.STOPPED
    assert snapshot.successful_start_order == snapshot.startup_plan
    assert snapshot.active_resource_order == ()
    assert all(
        resource.lifecycle_state is LifecycleState.STOPPED
        for resource in snapshot.resources
    )
    assert tuple(event.sequence for event in snapshot.events) == tuple(
        range(len(snapshot.events))
    )
    assert snapshot.event_high_water_mark == len(snapshot.events) - 1
    assert tuple(event.operation for event in snapshot.events[-8:]) == (
        RuntimeEventOperation.RUNTIME_SHUTDOWN,
        RuntimeEventOperation.RESOURCE_SHUTDOWN,
        RuntimeEventOperation.RESOURCE_SHUTDOWN,
        RuntimeEventOperation.RESOURCE_SHUTDOWN,
        RuntimeEventOperation.RESOURCE_SHUTDOWN,
        RuntimeEventOperation.RESOURCE_SHUTDOWN,
        RuntimeEventOperation.RESOURCE_SHUTDOWN,
        RuntimeEventOperation.RUNTIME_STOPPED,
    )


@pytest.mark.asyncio
async def test_snapshot_after_startup_failure_preserves_rollback_and_sanitization() -> None:
    operations, _, _, calls = _resource_operations(fail_start={"b"})

    with pytest.raises(RuntimeStartupError):
        await operations.start()

    snapshot = operations.snapshot()

    assert calls == ["start:a", "start:b", "shutdown:a"]
    assert snapshot.manager_state is RuntimeManagerState.FAILED
    assert snapshot.successful_start_order == (ResourceIdentity("a"),)
    assert snapshot.active_resource_order == ()
    assert tuple(resource.lifecycle_state for resource in snapshot.resources) == (
        LifecycleState.STOPPED,
        LifecycleState.FAILED,
        LifecycleState.CREATED,
    )
    assert snapshot.resources[1].health_summary == "backend unavailable during startup"
    assert tuple(event.operation for event in snapshot.events) == (
        RuntimeEventOperation.RUNTIME_START,
        RuntimeEventOperation.RESOURCE_START,
        RuntimeEventOperation.RESOURCE_START,
        RuntimeEventOperation.RESOURCE_START,
        RuntimeEventOperation.RESOURCE_START,
        RuntimeEventOperation.STARTUP_ROLLBACK,
        RuntimeEventOperation.RESOURCE_SHUTDOWN,
        RuntimeEventOperation.RESOURCE_SHUTDOWN,
        RuntimeEventOperation.STARTUP_ROLLBACK,
        RuntimeEventOperation.RUNTIME_FAILED,
    )
    assert snapshot.events[5].outcome is RuntimeEventOutcome.ATTEMPTED
    assert snapshot.events[8].outcome is RuntimeEventOutcome.COMPLETED
    assert snapshot.event_high_water_mark == 9
    assert "/dev/private" not in repr(snapshot)
    assert "top-secret" not in repr(snapshot)


@pytest.mark.asyncio
async def test_snapshot_after_shutdown_failure_remains_available_and_truthful() -> None:
    operations, _, _, calls = _resource_operations(fail_shutdown={"a", "c"})
    await operations.start()

    with pytest.raises(RuntimeShutdownError):
        await operations.shutdown()

    snapshot = operations.snapshot()

    assert calls[-3:] == ["shutdown:c", "shutdown:b", "shutdown:a"]
    assert snapshot.manager_state is RuntimeManagerState.FAILED
    assert snapshot.active_resource_order == ()
    assert tuple(resource.lifecycle_state for resource in snapshot.resources) == (
        LifecycleState.FAILED,
        LifecycleState.STOPPED,
        LifecycleState.FAILED,
    )
    assert snapshot.resources[0].health_summary == "backend unavailable during shutdown"
    assert snapshot.resources[2].health_summary == "backend unavailable during shutdown"
    assert snapshot.events[-1].operation is RuntimeEventOperation.RUNTIME_FAILED
    assert snapshot.events[-1].outcome is RuntimeEventOutcome.FAILED
    assert "/dev/private" not in repr(snapshot)
    assert "top-secret" not in repr(snapshot)


@pytest.mark.asyncio
async def test_snapshots_remain_available_after_safe_stop_success_and_failure() -> None:
    successful, successful_calls = _motor_operations(fail_stop=False)
    failing, failing_calls = _motor_operations(fail_stop=True)
    await successful.start()
    await failing.start()

    await successful.safe_stop()
    with pytest.raises(RuntimeSafeStopError):
        await failing.safe_stop()

    successful_snapshot = successful.snapshot()
    failing_snapshot = failing.snapshot()

    assert successful_calls[-1] == "safe-stop:motor"
    assert failing_calls[-1] == "safe-stop:motor"
    assert successful_snapshot.manager_state is RuntimeManagerState.RUNNING
    assert failing_snapshot.manager_state is RuntimeManagerState.RUNNING
    assert successful_snapshot.active_resource_order == (ResourceIdentity("motor"),)
    assert failing_snapshot.active_resource_order == (ResourceIdentity("motor"),)
    assert failing_snapshot.resources[0].health_status is HealthStatus.UNHEALTHY
    assert failing_snapshot.resources[0].health_summary == "safe-stop failed during safe-stop"
    assert "/dev/private" not in repr(failing_snapshot)
    assert "top-secret" not in repr(failing_snapshot)


@pytest.mark.asyncio
async def test_operations_instances_keep_events_and_state_independent() -> None:
    first, _, _, _ = _resource_operations(names=("one",))
    second, _, _, _ = _resource_operations(names=("one",))

    await first.start()

    assert first.snapshot().manager_state is RuntimeManagerState.RUNNING
    assert first.snapshot().event_high_water_mark == 3
    assert second.snapshot().manager_state is RuntimeManagerState.NEW
    assert second.snapshot().event_high_water_mark is None
    assert second.snapshot().events == ()


@pytest.mark.asyncio
async def test_zero_resource_runtime_has_deterministic_lifecycle_snapshots() -> None:
    operations = RuntimeOperations(
        RuntimeConfig(schema_version="1", resources=[]),
        ModelRegistry(),
    )

    assert operations.snapshot().resources == ()
    await operations.start()
    running = operations.snapshot()
    await operations.shutdown()
    stopped = operations.snapshot()

    assert running.manager_state is RuntimeManagerState.RUNNING
    assert running.startup_plan == running.successful_start_order == ()
    assert running.active_resource_order == ()
    assert tuple(event.operation for event in running.events) == (
        RuntimeEventOperation.RUNTIME_START,
        RuntimeEventOperation.RUNTIME_RUNNING,
    )
    assert stopped.manager_state is RuntimeManagerState.STOPPED
    assert tuple(event.operation for event in stopped.events[-2:]) == (
        RuntimeEventOperation.RUNTIME_SHUTDOWN,
        RuntimeEventOperation.RUNTIME_STOPPED,
    )


def _resource_operations(
    *,
    names: tuple[str, ...] = ("c", "b", "a"),
    fail_start: set[str] | None = None,
    fail_shutdown: set[str] | None = None,
    health_details: dict[str, str] | None = None,
) -> tuple[
    RuntimeOperations,
    dict[str, ControlledResource],
    list[str],
    list[str],
]:
    start_failures = fail_start or set()
    shutdown_failures = fail_shutdown or set()
    details = health_details or {}
    resources: dict[str, ControlledResource] = {}
    creations: list[str] = []
    calls: list[str] = []

    def factory(definition: ResourceDefinition) -> Resource:
        identity = definition.identity.value
        creations.append(identity)
        resource = ControlledResource(
            definition.identity,
            calls,
            fail_start=identity in start_failures,
            fail_shutdown=identity in shutdown_failures,
            health_detail=details.get(identity),
        )
        resources[identity] = resource
        return resource

    registry = ModelRegistry()
    registry.register("test.resource", factory)
    definitions = {
        "a": ResourceDefinition(
            identity=ResourceIdentity("a"), model="test.resource", settings={}
        ),
        "b": ResourceDefinition(
            identity=ResourceIdentity("b"),
            model="test.resource",
            settings={},
            depends_on=(ResourceIdentity("a"),),
        ),
        "c": ResourceDefinition(
            identity=ResourceIdentity("c"),
            model="test.resource",
            settings={},
            depends_on=(ResourceIdentity("b"),),
        ),
        "one": ResourceDefinition(
            identity=ResourceIdentity("one"), model="test.resource", settings={}
        ),
    }
    config = RuntimeConfig(
        schema_version="1",
        resources=[definitions[name] for name in names],
    )
    return RuntimeOperations(config, registry), resources, creations, calls


def _motor_operations(*, fail_stop: bool) -> tuple[RuntimeOperations, list[str]]:
    calls: list[str] = []

    def factory(definition: ResourceDefinition) -> Resource:
        return ControlledMotor(definition.identity, calls, fail_stop=fail_stop)

    registry = ModelRegistry()
    registry.register("test.motor", factory)
    config = RuntimeConfig(
        schema_version="1",
        resources=[
            ResourceDefinition(
                identity=ResourceIdentity("motor"),
                model="test.motor",
                settings={},
            )
        ],
    )
    return RuntimeOperations(config, registry), calls
