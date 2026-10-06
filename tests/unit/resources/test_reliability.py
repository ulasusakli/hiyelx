import asyncio
from dataclasses import FrozenInstanceError

import pytest

from hiyelx.resources import (
    BackendUnavailableError,
    HealthStatus,
    InvalidDeadlineError,
    LifecycleState,
    OperationDeadlineExceeded,
    OperationDeadlinePolicy,
    Resource,
    ResourceIdentity,
    ResourceShutdownError,
    ResourceStartupError,
)


class ControlledResource(Resource):
    def __init__(
        self,
        identity: ResourceIdentity,
        *,
        start_gate: asyncio.Event | None = None,
        shutdown_gate: asyncio.Event | None = None,
        deadline_policy: OperationDeadlinePolicy,
    ) -> None:
        super().__init__(identity, deadline_policy=deadline_policy)
        self.start_gate = start_gate
        self.shutdown_gate = shutdown_gate

    async def _on_start(self) -> None:
        if self.start_gate is not None:
            await self.start_gate.wait()

    async def _on_shutdown(self) -> None:
        if self.shutdown_gate is not None:
            await self.shutdown_gate.wait()


class UnavailableResource(Resource):
    failure = BackendUnavailableError("backend-specific detail")

    async def _on_start(self) -> None:
        raise self.failure


def _policy(**overrides: float) -> OperationDeadlinePolicy:
    values = {
        "startup_seconds": 0.01,
        "shutdown_seconds": 0.01,
        "motor_command_seconds": 0.01,
        "motor_state_read_seconds": 0.01,
        "transport_operation_seconds": 0.01,
    }
    values.update(overrides)
    return OperationDeadlinePolicy(**values)


@pytest.mark.parametrize(
    "value",
    [0.0, -1.0, float("nan"), float("inf"), float("-inf"), True, "1"],
)
def test_deadline_policy_rejects_invalid_values_before_work(value: object) -> None:
    with pytest.raises(InvalidDeadlineError) as caught:
        OperationDeadlinePolicy(startup_seconds=value)  # type: ignore[arg-type]

    assert caught.value.field == "startup_seconds"
    assert caught.value.value == value or value != value


def test_deadline_policy_is_immutable() -> None:
    policy = OperationDeadlinePolicy()

    with pytest.raises(FrozenInstanceError):
        policy.startup_seconds = 1.0  # type: ignore[misc]


@pytest.mark.asyncio
async def test_startup_deadline_sets_failed_state_and_unhealthy_snapshot() -> None:
    identity = ResourceIdentity("slow-start")
    resource = ControlledResource(
        identity,
        start_gate=asyncio.Event(),
        deadline_policy=_policy(),
    )

    with pytest.raises(ResourceStartupError) as caught:
        await resource.start()

    timeout = caught.value.__cause__
    assert isinstance(timeout, OperationDeadlineExceeded)
    assert isinstance(timeout.__cause__, TimeoutError)
    assert timeout.identity is identity
    assert timeout.operation == "startup"
    assert timeout.configured_timeout_seconds == 0.01
    assert timeout.lifecycle_state is LifecycleState.STARTING
    assert resource.state is LifecycleState.FAILED
    assert resource.health.status is HealthStatus.UNHEALTHY
    assert resource.health.detail == "deadline exceeded during startup"


@pytest.mark.asyncio
async def test_shutdown_deadline_sets_failed_state_and_unhealthy_snapshot() -> None:
    resource = ControlledResource(
        ResourceIdentity("slow-shutdown"),
        shutdown_gate=asyncio.Event(),
        deadline_policy=_policy(),
    )
    await resource.start()

    with pytest.raises(ResourceShutdownError) as caught:
        await resource.shutdown()

    timeout = caught.value.__cause__
    assert isinstance(timeout, OperationDeadlineExceeded)
    assert timeout.operation == "shutdown"
    assert timeout.lifecycle_state is LifecycleState.STOPPING
    assert resource.state is LifecycleState.FAILED
    assert resource.health.status is HealthStatus.UNHEALTHY
    assert resource.health.detail == "deadline exceeded during shutdown"


@pytest.mark.asyncio
async def test_backend_unavailability_is_visible_without_leaking_detail() -> None:
    resource = UnavailableResource(ResourceIdentity("offline"))

    with pytest.raises(ResourceStartupError) as caught:
        await resource.start()

    assert caught.value.__cause__ is resource.failure
    assert resource.health.status is HealthStatus.UNHEALTHY
    assert resource.health.detail == "backend unavailable during startup"
    assert "backend-specific" not in (resource.health.detail or "")
