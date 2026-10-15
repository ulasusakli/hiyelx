from dataclasses import FrozenInstanceError

import pytest

from hiyelx.components import Motor, MotorCommand, MotorState
from hiyelx.config import ResourceDefinition, RuntimeConfig
from hiyelx.models import ModelRegistry
from hiyelx.resources import (
    HealthStatus,
    LifecycleState,
    Resource,
    ResourceFaultKind,
    ResourceIdentity,
    ResourceOperation,
)
from hiyelx.runtime import (
    LocalEventRecorder,
    RuntimeEventOperation,
    RuntimeEventOutcome,
    RuntimeManager,
    RuntimeSafeStopError,
)


class ControlledMotor(Motor):
    def __init__(
        self,
        identity: ResourceIdentity,
        operations: list[str],
        *,
        fail_stop: bool = False,
        secret: str = "",
    ) -> None:
        super().__init__(identity)
        self._operations = operations
        self._fail_stop = fail_stop
        self._secret = secret

    async def _on_start(self) -> None:
        self._operations.append(f"start:{self.identity!s}")

    async def _apply_command(self, command: MotorCommand) -> None:
        assert command == MotorCommand.zero_velocity()
        self._operations.append(f"stop:{self.identity!s}")
        if self._fail_stop:
            raise RuntimeError(f"vendor failure {self._secret}")

    async def _read_state(self) -> MotorState:
        return MotorState(0.0, 0.0)


class ControlledResource(Resource):
    def __init__(self, identity: ResourceIdentity, operations: list[str]) -> None:
        super().__init__(identity)
        self._operations = operations

    async def _on_start(self) -> None:
        self._operations.append(f"start:{self.identity!s}")


@pytest.mark.asyncio
async def test_safe_stop_uses_reverse_successful_start_order_and_ignores_non_motors() -> None:
    operations: list[str] = []
    manager, _ = _manager(operations)
    await manager.start()
    operations.clear()

    report = await manager.safe_stop()

    assert operations == ["stop:motor-b", "stop:motor-a"]
    assert tuple(outcome.identity.value for outcome in report.outcomes) == (
        "motor-b",
        "motor-a",
    )
    assert all(outcome.succeeded for outcome in report.outcomes)

    await manager.shutdown()
    assert all(
        resource.state is LifecycleState.STOPPED
        for resource in manager.owned_resources.values()
    )


@pytest.mark.asyncio
async def test_stop_failures_are_ordered_and_do_not_prevent_later_attempts() -> None:
    operations: list[str] = []
    manager, motors = _manager(operations, fail_stops={"motor-a", "motor-b"})
    await manager.start()
    operations.clear()

    with pytest.raises(RuntimeSafeStopError) as caught:
        await manager.safe_stop()

    assert operations == ["stop:motor-b", "stop:motor-a"]
    assert tuple(outcome.identity.value for outcome in caught.value.report.failures) == (
        "motor-b",
        "motor-a",
    )
    assert caught.value.__cause__ is caught.value.report.failures[0].error
    assert all(motor.health.status is HealthStatus.UNHEALTHY for motor in motors.values())
    assert all(
        motor.health.detail == "safe-stop failed during safe-stop"
        for motor in motors.values()
    )


@pytest.mark.asyncio
async def test_primary_failure_is_preserved_after_successful_cleanup() -> None:
    manager, _ = _manager([])
    await manager.start()
    trigger = ValueError("primary application failure")

    with pytest.raises(RuntimeSafeStopError) as caught:
        await manager.safe_stop(primary_failure=trigger)

    assert caught.value.primary_failure is trigger
    assert caught.value.__cause__ is trigger
    assert caught.value.report.failures == ()


@pytest.mark.asyncio
async def test_repeated_safe_stop_is_idempotent_and_performs_no_new_motor_io() -> None:
    operations: list[str] = []
    manager, _ = _manager(operations)
    await manager.start()
    operations.clear()

    first = await manager.safe_stop()
    second = await manager.safe_stop()

    assert second is first
    assert operations == ["stop:motor-b", "stop:motor-a"]


@pytest.mark.asyncio
async def test_repeated_failed_safe_stop_does_not_retry_and_success_preserves_fault() -> None:
    operations: list[str] = []
    manager, motors = _manager(operations, fail_stops={"motor-b"})
    await manager.start()
    motors["motor-a"].record_fault(
        ResourceFaultKind.BACKEND_UNAVAILABLE,
        ResourceOperation.MOTOR_COMMAND,
    )
    operations.clear()

    for _ in range(2):
        with pytest.raises(RuntimeSafeStopError):
            await manager.safe_stop()

    assert operations == ["stop:motor-b", "stop:motor-a"]
    assert motors["motor-a"].health.detail == "backend unavailable during motor command"


@pytest.mark.asyncio
async def test_events_are_deterministic_immutable_sanitized_and_instance_local() -> None:
    first_recorder = LocalEventRecorder()
    second_recorder = LocalEventRecorder()
    first, _ = _manager(
        [],
        fail_stops={"motor-b"},
        secret="device=/dev/private credential=top-secret",
        recorder=first_recorder,
    )
    second, _ = _manager([], recorder=second_recorder)
    await first.start()
    await second.start()

    with pytest.raises(RuntimeSafeStopError):
        await first.safe_stop()

    events = first_recorder.events
    assert tuple(event.sequence for event in events) == tuple(range(len(events)))
    assert tuple((event.operation, event.outcome) for event in events) == (
        (RuntimeEventOperation.RUNTIME_START, RuntimeEventOutcome.REQUESTED),
        (RuntimeEventOperation.RESOURCE_START, RuntimeEventOutcome.ATTEMPTED),
        (RuntimeEventOperation.RESOURCE_START, RuntimeEventOutcome.SUCCEEDED),
        (RuntimeEventOperation.RESOURCE_START, RuntimeEventOutcome.ATTEMPTED),
        (RuntimeEventOperation.RESOURCE_START, RuntimeEventOutcome.SUCCEEDED),
        (RuntimeEventOperation.RESOURCE_START, RuntimeEventOutcome.ATTEMPTED),
        (RuntimeEventOperation.RESOURCE_START, RuntimeEventOutcome.SUCCEEDED),
        (RuntimeEventOperation.RUNTIME_RUNNING, RuntimeEventOutcome.SUCCEEDED),
        (RuntimeEventOperation.SAFE_STOP, RuntimeEventOutcome.REQUESTED),
        (RuntimeEventOperation.SAFE_STOP, RuntimeEventOutcome.ATTEMPTED),
        (RuntimeEventOperation.HEALTH_DEGRADATION, RuntimeEventOutcome.FAILED),
        (RuntimeEventOperation.SAFE_STOP, RuntimeEventOutcome.FAILED),
        (RuntimeEventOperation.SAFE_STOP, RuntimeEventOutcome.ATTEMPTED),
        (RuntimeEventOperation.SAFE_STOP, RuntimeEventOutcome.SUCCEEDED),
        (RuntimeEventOperation.SAFE_STOP_CLEANUP, RuntimeEventOutcome.COMPLETED),
    )
    assert all("/dev/private" not in event.summary for event in events)
    assert all("top-secret" not in event.summary for event in events)
    assert tuple(event.operation for event in second_recorder.events) == (
        RuntimeEventOperation.RUNTIME_START,
        RuntimeEventOperation.RESOURCE_START,
        RuntimeEventOperation.RESOURCE_START,
        RuntimeEventOperation.RESOURCE_START,
        RuntimeEventOperation.RESOURCE_START,
        RuntimeEventOperation.RESOURCE_START,
        RuntimeEventOperation.RESOURCE_START,
        RuntimeEventOperation.RUNTIME_RUNNING,
    )
    assert all(
        event.operation is not RuntimeEventOperation.SAFE_STOP
        for event in second_recorder.events
    )
    assert events[10].health_status is HealthStatus.UNHEALTHY

    with pytest.raises(FrozenInstanceError):
        events[0].summary = "changed"  # type: ignore[misc]


def _manager(
    operations: list[str],
    *,
    fail_stops: set[str] | None = None,
    secret: str = "",
    recorder: LocalEventRecorder | None = None,
) -> tuple[RuntimeManager, dict[str, ControlledMotor]]:
    failures = fail_stops or set()
    motors: dict[str, ControlledMotor] = {}

    def motor_factory(definition: ResourceDefinition) -> Resource:
        motor = ControlledMotor(
            definition.identity,
            operations,
            fail_stop=definition.identity.value in failures,
            secret=secret,
        )
        motors[definition.identity.value] = motor
        return motor

    def resource_factory(definition: ResourceDefinition) -> Resource:
        return ControlledResource(definition.identity, operations)

    registry = ModelRegistry()
    registry.register("test.motor", motor_factory)
    registry.register("test.resource", resource_factory)
    config = RuntimeConfig(
        schema_version="1",
        resources=[
            ResourceDefinition(
                identity=ResourceIdentity("motor-a"),
                model="test.motor",
                settings={},
            ),
            ResourceDefinition(
                identity=ResourceIdentity("service"),
                model="test.resource",
                settings={},
                depends_on=(ResourceIdentity("motor-a"),),
            ),
            ResourceDefinition(
                identity=ResourceIdentity("motor-b"),
                model="test.motor",
                settings={},
                depends_on=(ResourceIdentity("service"),),
            ),
        ],
    )
    return RuntimeManager(config, registry, event_sink=recorder), motors
