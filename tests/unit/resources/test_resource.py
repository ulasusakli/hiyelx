from collections.abc import Sequence

import pytest

from hiyelx.resources import (
    LIFECYCLE_TRANSITIONS,
    HealthStatus,
    InvalidLifecycleTransition,
    LifecycleState,
    Resource,
    ResourceHealth,
    ResourceIdentity,
    ResourceShutdownError,
    ResourceStartupError,
)


class RecordingResource(Resource):
    def __init__(
        self,
        identity: ResourceIdentity,
        events: list[LifecycleState] | None = None,
    ) -> None:
        super().__init__(identity)
        self.events = events if events is not None else []

    async def _on_start(self) -> None:
        self.events.append(self.state)

    async def _on_shutdown(self) -> None:
        self.events.append(self.state)

    def publish_health(self, health: ResourceHealth) -> None:
        self._set_health(health)


class FailingStartupResource(Resource):
    failure = RuntimeError("startup failed")

    async def _on_start(self) -> None:
        raise self.failure


class FailingShutdownResource(Resource):
    failure = RuntimeError("shutdown failed")

    async def _on_shutdown(self) -> None:
        raise self.failure


def test_identity_and_initial_state() -> None:
    identity = ResourceIdentity("drive/left")
    resource = Resource(identity)

    assert resource.identity is identity
    assert str(resource.identity) == "drive/left"
    assert resource.state is LifecycleState.CREATED
    assert resource.health == ResourceHealth(HealthStatus.UNKNOWN)


@pytest.mark.asyncio
async def test_successful_startup_and_shutdown() -> None:
    resource = Resource(ResourceIdentity("camera/front"))

    await resource.start()
    assert resource.state is LifecycleState.RUNNING

    await resource.shutdown()
    assert resource.state is LifecycleState.STOPPED


@pytest.mark.asyncio
async def test_hooks_observe_transition_ordering() -> None:
    events: list[LifecycleState] = []
    resource = RecordingResource(ResourceIdentity("arm"), events)

    await resource.start()
    await resource.shutdown()

    assert events == [LifecycleState.STARTING, LifecycleState.STOPPING]
    assert LIFECYCLE_TRANSITIONS[LifecycleState.STOPPED] == frozenset()
    assert LIFECYCLE_TRANSITIONS[LifecycleState.FAILED] == frozenset()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("initial_operation", "invalid_operation", "expected_state", "target_state"),
    [
        (None, "shutdown", LifecycleState.CREATED, LifecycleState.STOPPING),
        ("start", "start", LifecycleState.RUNNING, LifecycleState.STARTING),
        ("cycle", "start", LifecycleState.STOPPED, LifecycleState.STARTING),
        ("cycle", "shutdown", LifecycleState.STOPPED, LifecycleState.STOPPING),
    ],
)
async def test_invalid_transitions_are_rejected_without_changing_state(
    initial_operation: str | None,
    invalid_operation: str,
    expected_state: LifecycleState,
    target_state: LifecycleState,
) -> None:
    resource = Resource(ResourceIdentity("invalid-transition"))
    await _prepare(resource, initial_operation)

    with pytest.raises(InvalidLifecycleTransition) as caught:
        if invalid_operation == "start":
            await resource.start()
        else:
            await resource.shutdown()

    assert caught.value.identity == resource.identity
    assert caught.value.current_state is expected_state
    assert caught.value.target_state is target_state
    assert resource.state is expected_state


@pytest.mark.asyncio
async def test_startup_failure_sets_failed_state_and_preserves_cause() -> None:
    resource = FailingStartupResource(ResourceIdentity("failing-startup"))

    with pytest.raises(ResourceStartupError) as caught:
        await resource.start()

    assert resource.state is LifecycleState.FAILED
    assert caught.value.identity == resource.identity
    assert caught.value.__cause__ is resource.failure


@pytest.mark.asyncio
async def test_shutdown_failure_sets_failed_state_and_preserves_cause() -> None:
    resource = FailingShutdownResource(ResourceIdentity("failing-shutdown"))
    await resource.start()

    with pytest.raises(ResourceShutdownError) as caught:
        await resource.shutdown()

    assert resource.state is LifecycleState.FAILED
    assert caught.value.identity == resource.identity
    assert caught.value.__cause__ is resource.failure


def test_health_inspection_returns_latest_snapshot() -> None:
    resource = RecordingResource(ResourceIdentity("health-source"))
    degraded = ResourceHealth(HealthStatus.DEGRADED, "temperature nearing limit")

    resource.publish_health(degraded)

    assert resource.health is degraded
    assert resource.health.status is HealthStatus.DEGRADED
    assert resource.health.detail == "temperature nearing limit"


async def _prepare(resource: Resource, operations: str | None) -> None:
    operation_order: Sequence[str] = () if operations is None else operations.split(",")
    if operation_order == ["cycle"]:
        operation_order = ("start", "shutdown")

    for operation in operation_order:
        if operation == "start":
            await resource.start()
        else:
            await resource.shutdown()
