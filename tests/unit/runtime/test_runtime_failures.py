import pytest

from hiyelx.config import ResourceDefinition, RuntimeConfig
from hiyelx.models import ModelRegistry
from hiyelx.resources import (
    HealthStatus,
    LifecycleState,
    Resource,
    ResourceIdentity,
    ResourceShutdownError,
    ResourceStartupError,
)
from hiyelx.runtime import (
    InvalidRuntimeManagerStateError,
    RuntimeManager,
    RuntimeManagerOperation,
    RuntimeManagerState,
    RuntimeShutdownError,
    RuntimeStartupError,
)


class ControlledResource(Resource):
    def __init__(
        self,
        identity: ResourceIdentity,
        events: list[str],
        *,
        fail_start: bool = False,
        fail_shutdown: bool = False,
    ) -> None:
        super().__init__(identity)
        self._events = events
        self._fail_start = fail_start
        self._fail_shutdown = fail_shutdown

    async def _on_start(self) -> None:
        self._events.append(f"start:{self.identity!s}")
        if self._fail_start:
            raise ValueError(f"start failure:{self.identity!s}")

    async def _on_shutdown(self) -> None:
        self._events.append(f"shutdown:{self.identity!s}")
        if self._fail_shutdown:
            raise ValueError(f"shutdown failure:{self.identity!s}")


@pytest.mark.asyncio
async def test_startup_failure_stops_and_rolls_back_started_prefix() -> None:
    events: list[str] = []
    manager, resources = _manager(events, fail_start={"b"})

    with pytest.raises(RuntimeStartupError) as caught:
        await manager.start()

    assert events == ["start:a", "start:b", "shutdown:a"]
    assert "start:c" not in events
    assert manager.state is RuntimeManagerState.FAILED
    assert manager.successful_start_order == (ResourceIdentity("a"),)
    assert isinstance(caught.value.primary_failure, ResourceStartupError)
    assert caught.value.__cause__ is caught.value.primary_failure
    assert isinstance(caught.value.primary_failure.__cause__, ValueError)
    assert caught.value.rollback_failures == ()
    assert resources["a"].state is LifecycleState.STOPPED
    assert resources["b"].state is LifecycleState.FAILED
    assert resources["c"].state is LifecycleState.CREATED


@pytest.mark.asyncio
async def test_rollback_continues_and_reports_failures_in_reverse_order() -> None:
    events: list[str] = []
    manager, resources = _manager(
        events,
        fail_start={"c"},
        fail_shutdown={"a", "b"},
    )

    with pytest.raises(RuntimeStartupError) as caught:
        await manager.start()

    assert events == [
        "start:a",
        "start:b",
        "start:c",
        "shutdown:b",
        "shutdown:a",
    ]
    assert tuple(failure.identity for failure in caught.value.rollback_failures) == (
        ResourceIdentity("b"),
        ResourceIdentity("a"),
    )
    assert all(
        isinstance(failure.error, ResourceShutdownError)
        for failure in caught.value.rollback_failures
    )
    assert resources["a"].state is LifecycleState.FAILED
    assert resources["b"].state is LifecycleState.FAILED
    assert manager.state is RuntimeManagerState.FAILED


@pytest.mark.asyncio
async def test_shutdown_continues_and_reports_every_failure_in_order() -> None:
    events: list[str] = []
    manager, resources = _manager(events, fail_shutdown={"a", "c"})
    await manager.start()
    events.clear()

    with pytest.raises(RuntimeShutdownError) as caught:
        await manager.shutdown()

    assert events == ["shutdown:c", "shutdown:b", "shutdown:a"]
    assert tuple(failure.identity for failure in caught.value.failures) == (
        ResourceIdentity("c"),
        ResourceIdentity("a"),
    )
    assert caught.value.__cause__ is caught.value.failures[0].error
    assert manager.state is RuntimeManagerState.FAILED
    assert resources["b"].state is LifecycleState.STOPPED
    assert resources["a"].state is LifecycleState.FAILED
    assert resources["c"].state is LifecycleState.FAILED
    assert resources["a"].health.status is HealthStatus.UNHEALTHY
    assert resources["a"].health.detail == "lifecycle cleanup failed during shutdown"
    assert resources["c"].health.status is HealthStatus.UNHEALTHY
    assert resources["c"].health.detail == "lifecycle cleanup failed during shutdown"


@pytest.mark.asyncio
async def test_shutdown_before_start_is_rejected_without_state_change() -> None:
    manager, _ = _manager([])

    with pytest.raises(InvalidRuntimeManagerStateError) as caught:
        await manager.shutdown()

    assert caught.value.operation is RuntimeManagerOperation.SHUTDOWN
    assert caught.value.current_state is RuntimeManagerState.NEW
    assert manager.state is RuntimeManagerState.NEW


@pytest.mark.asyncio
async def test_start_twice_is_rejected_without_state_change() -> None:
    manager, _ = _manager([])
    await manager.start()

    with pytest.raises(InvalidRuntimeManagerStateError):
        await manager.start()

    assert manager.state is RuntimeManagerState.RUNNING


@pytest.mark.asyncio
async def test_shutdown_twice_and_restart_after_stop_are_rejected() -> None:
    manager, _ = _manager([])
    await manager.start()
    await manager.shutdown()

    with pytest.raises(InvalidRuntimeManagerStateError):
        await manager.shutdown()
    with pytest.raises(InvalidRuntimeManagerStateError):
        await manager.start()

    assert manager.state is RuntimeManagerState.STOPPED


@pytest.mark.asyncio
async def test_start_and_shutdown_after_failed_startup_are_rejected() -> None:
    manager, _ = _manager([], fail_start={"a"})
    with pytest.raises(RuntimeStartupError):
        await manager.start()

    with pytest.raises(InvalidRuntimeManagerStateError):
        await manager.start()
    with pytest.raises(InvalidRuntimeManagerStateError):
        await manager.shutdown()

    assert manager.state is RuntimeManagerState.FAILED


def _manager(
    events: list[str],
    *,
    fail_start: set[str] | None = None,
    fail_shutdown: set[str] | None = None,
) -> tuple[RuntimeManager, dict[str, ControlledResource]]:
    start_failures = fail_start or set()
    shutdown_failures = fail_shutdown or set()
    resources: dict[str, ControlledResource] = {}

    def factory(definition: ResourceDefinition) -> Resource:
        identity = definition.identity.value
        resource = ControlledResource(
            definition.identity,
            events,
            fail_start=identity in start_failures,
            fail_shutdown=identity in shutdown_failures,
        )
        resources[identity] = resource
        return resource

    registry = ModelRegistry()
    registry.register("test.resource", factory)
    config = RuntimeConfig(
        schema_version="1",
        resources=[
            ResourceDefinition(
                identity=ResourceIdentity(identity),
                model="test.resource",
                settings={},
            )
            for identity in ("a", "b", "c")
        ],
    )
    return RuntimeManager(config, registry), resources
