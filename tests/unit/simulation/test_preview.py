import asyncio
from dataclasses import FrozenInstanceError

import pytest

from hiyelx.components import MotorCommand
from hiyelx.config import ResourceDefinition, RuntimeConfig
from hiyelx.models import ModelRegistry
from hiyelx.resources import (
    HealthStatus,
    LifecycleState,
    Resource,
    ResourceFaultKind,
    ResourceHealth,
    ResourceIdentity,
    ResourceOperation,
)
from hiyelx.runtime import LocalEventRecorder, RuntimeManager, RuntimeManagerState
from hiyelx.simulation import (
    SIMULATED_MOTOR_MODEL,
    InvalidSimulationPreviewSnapshotError,
    SimulatedMotor,
    SimulationMotorPreviewState,
    SimulationPreviewProvider,
    SimulationPreviewResourceSnapshot,
    SimulationPreviewSnapshot,
    SimulationPreviewUnavailableError,
    UnsupportedSimulationPreviewResourceError,
    register_simulated_motor,
    render_simulation_preview_json,
)


def test_preview_value_objects_are_frozen_and_strict() -> None:
    resource = _preview_resource("sim_motor")
    snapshot = SimulationPreviewSnapshot(
        schema_version="1",
        runtime_state=RuntimeManagerState.RUNNING,
        resources=(resource,),
    )

    with pytest.raises(FrozenInstanceError):
        resource.kind = "motor"  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        snapshot.runtime_state = RuntimeManagerState.STOPPED  # type: ignore[misc]

    with pytest.raises(InvalidSimulationPreviewSnapshotError) as version_error:
        SimulationPreviewSnapshot(
            schema_version=1,  # type: ignore[arg-type]
            runtime_state=RuntimeManagerState.RUNNING,
            resources=(resource,),
        )
    assert version_error.value.field == "schema_version"

    with pytest.raises(InvalidSimulationPreviewSnapshotError) as tuple_error:
        SimulationPreviewSnapshot(
            schema_version="1",
            runtime_state=RuntimeManagerState.RUNNING,
            resources=[resource],  # type: ignore[arg-type]
        )
    assert tuple_error.value.field == "resources"

    with pytest.raises(InvalidSimulationPreviewSnapshotError) as duplicate_error:
        SimulationPreviewSnapshot(
            schema_version="1",
            runtime_state=RuntimeManagerState.RUNNING,
            resources=(resource, resource),
        )
    assert duplicate_error.value.field == "resources"

    with pytest.raises(InvalidSimulationPreviewSnapshotError) as summary_error:
        SimulationPreviewResourceSnapshot(
            identity=ResourceIdentity("sim_motor"),
            kind="motor",
            lifecycle_state=LifecycleState.RUNNING,
            health_status=HealthStatus.DEGRADED,
            health_summary="device=/dev/private credential=secret",
            state=SimulationMotorPreviewState(0.0, 0.0, 0.0, 0),
        )
    assert summary_error.value.field == "health_summary"


@pytest.mark.parametrize("schema_version", [True, 1.0, "2"])
def test_preview_schema_version_rejects_non_v1_values(
    schema_version: object,
) -> None:
    with pytest.raises(InvalidSimulationPreviewSnapshotError) as caught:
        SimulationPreviewSnapshot(
            schema_version=schema_version,  # type: ignore[arg-type]
            runtime_state=RuntimeManagerState.RUNNING,
            resources=(),
        )

    assert caught.value.field == "schema_version"


def test_canonical_json_is_exact_and_has_one_trailing_newline() -> None:
    snapshot = SimulationPreviewSnapshot(
        schema_version="1",
        runtime_state=RuntimeManagerState.RUNNING,
        resources=(
            SimulationPreviewResourceSnapshot(
                identity=ResourceIdentity("sim_motor"),
                kind="motor",
                lifecycle_state=LifecycleState.RUNNING,
                health_status=HealthStatus.HEALTHY,
                health_summary=None,
                state=SimulationMotorPreviewState(1.5, 0.5, 2.0, 3),
            ),
        ),
    )

    rendered = render_simulation_preview_json(snapshot)

    assert rendered == (
        '{"resources":[{"health_status":"healthy","health_summary":null,'
        '"identity":"sim_motor","kind":"motor","lifecycle_state":"running",'
        '"state":{"angular_position_radians":1.5,'
        '"angular_velocity_radians_per_second":0.5,"revision":3,'
        '"simulation_time_seconds":2.0}}],"runtime_state":"running",'
        '"schema_version":"1"}\n'
    )
    assert rendered.count("\n") == 1


def test_provider_before_start_is_ordered_and_observation_only() -> None:
    recorder = LocalEventRecorder()
    runtime = _simulated_runtime("z_motor", "a_motor", event_sink=recorder)
    provider = SimulationPreviewProvider(runtime)

    first = provider.snapshot()
    second = provider.snapshot()

    assert first == second
    assert first.runtime_state is RuntimeManagerState.NEW
    assert tuple(resource.identity.value for resource in first.resources) == (
        "a_motor",
        "z_motor",
    )
    assert all(
        resource.lifecycle_state is LifecycleState.CREATED
        for resource in first.resources
    )
    assert all(
        resource.health_status is HealthStatus.UNKNOWN for resource in first.resources
    )
    assert all(
        resource.state == SimulationMotorPreviewState(0.0, 0.0, 0.0, 0)
        for resource in first.resources
    )
    assert recorder.events == ()


@pytest.mark.asyncio
async def test_equivalent_runtime_sequences_render_byte_equal_preview() -> None:
    first_runtime = _simulated_runtime("sim_motor")
    second_runtime = _simulated_runtime("sim_motor")
    await first_runtime.start()
    await second_runtime.start()
    first_motor = first_runtime.get_resource(ResourceIdentity("sim_motor"))
    second_motor = second_runtime.get_resource(ResourceIdentity("sim_motor"))
    assert isinstance(first_motor, SimulatedMotor)
    assert isinstance(second_motor, SimulatedMotor)

    for motor in (first_motor, second_motor):
        await motor.apply_command(MotorCommand(1.5))
        motor.advance_time(2.0)
        await motor.apply_command(MotorCommand(-0.5))
        motor.advance_time(1.0)
        await motor.stop()

    first_snapshot = SimulationPreviewProvider(first_runtime).snapshot()
    second_snapshot = SimulationPreviewProvider(second_runtime).snapshot()

    assert first_snapshot == second_snapshot
    assert render_simulation_preview_json(
        first_snapshot
    ) == render_simulation_preview_json(second_snapshot)


@pytest.mark.asyncio
async def test_provider_running_snapshot_preserves_state_events_and_health() -> None:
    recorder = LocalEventRecorder()
    runtime = _simulated_runtime("sim_motor", event_sink=recorder)
    provider = SimulationPreviewProvider(runtime)
    await runtime.start()
    motor = runtime.get_resource(ResourceIdentity("sim_motor"))
    assert isinstance(motor, SimulatedMotor)
    await motor.apply_command(MotorCommand(2.0))
    motor.advance_time(1.25)
    motor.record_fault(ResourceFaultKind.SAFE_STOP, ResourceOperation.SAFE_STOP)
    state_before = motor.preview_state()
    events_before = recorder.events

    first = provider.snapshot()
    second = provider.snapshot()

    assert first == second
    assert first.runtime_state is RuntimeManagerState.RUNNING
    assert first.resources == (
        SimulationPreviewResourceSnapshot(
            identity=ResourceIdentity("sim_motor"),
            kind="motor",
            lifecycle_state=LifecycleState.RUNNING,
            health_status=HealthStatus.UNHEALTHY,
            health_summary="safe-stop failed during safe-stop",
            state=SimulationMotorPreviewState(2.5, 2.0, 1.25, 2),
        ),
    )
    assert motor.preview_state() == state_before
    assert recorder.events == events_before


@pytest.mark.asyncio
async def test_provider_omits_backend_authored_health_detail() -> None:
    unsafe = "device=/dev/private credential=top-secret"
    registry = ModelRegistry()
    registry.register(
        "motor.unsafe-preview-test",
        lambda definition: _UnsafeHealthSimulatedMotor(definition.identity, unsafe),
    )
    runtime = RuntimeManager(
        _runtime_config(("sim_motor", "motor.unsafe-preview-test")),
        registry,
    )
    await runtime.start()

    snapshot = SimulationPreviewProvider(runtime).snapshot()
    rendered = render_simulation_preview_json(snapshot)

    assert snapshot.resources[0].health_status is HealthStatus.DEGRADED
    assert snapshot.resources[0].health_summary is None
    assert unsafe not in repr(snapshot)
    assert unsafe not in rendered


def test_provider_rejects_non_simulated_resources() -> None:
    registry = ModelRegistry()
    registry.register("resource.plain", lambda definition: Resource(definition.identity))
    runtime = RuntimeManager(_runtime_config(("plain", "resource.plain")), registry)

    with pytest.raises(UnsupportedSimulationPreviewResourceError) as caught:
        SimulationPreviewProvider(runtime).snapshot()

    assert caught.value.identity == ResourceIdentity("plain")


@pytest.mark.asyncio
async def test_provider_rejects_transitional_runtime_without_waiting() -> None:
    entered = asyncio.Event()
    release = asyncio.Event()
    registry = ModelRegistry()
    registry.register(
        "motor.blocking-preview-test",
        lambda definition: _BlockingStartSimulatedMotor(
            definition.identity,
            entered=entered,
            release=release,
        ),
    )
    runtime = RuntimeManager(
        _runtime_config(("sim_motor", "motor.blocking-preview-test")),
        registry,
    )
    start_task = asyncio.create_task(runtime.start())
    await entered.wait()

    with pytest.raises(SimulationPreviewUnavailableError):
        SimulationPreviewProvider(runtime).snapshot()

    release.set()
    await start_task


@pytest.mark.asyncio
async def test_provider_rejects_overlapping_motor_mutation_without_retry() -> None:
    registry = ModelRegistry()
    registry.register(
        "motor.mutating-preview-test",
        lambda definition: _MutatingPreviewMotor(definition.identity),
    )
    runtime = RuntimeManager(
        _runtime_config(("sim_motor", "motor.mutating-preview-test")),
        registry,
    )
    await runtime.start()
    motor = runtime.get_resource(ResourceIdentity("sim_motor"))
    assert isinstance(motor, _MutatingPreviewMotor)

    with pytest.raises(SimulationPreviewUnavailableError):
        SimulationPreviewProvider(runtime).snapshot()

    assert motor.preview_calls == 2
    assert motor.preview_state().revision == 1


class _UnsafeHealthSimulatedMotor(SimulatedMotor):
    def __init__(self, identity: ResourceIdentity, detail: str) -> None:
        super().__init__(identity)
        self._detail = detail

    async def _on_start(self) -> None:
        await super()._on_start()
        self._set_health(ResourceHealth(HealthStatus.DEGRADED, self._detail))


class _BlockingStartSimulatedMotor(SimulatedMotor):
    def __init__(
        self,
        identity: ResourceIdentity,
        *,
        entered: asyncio.Event,
        release: asyncio.Event,
    ) -> None:
        super().__init__(identity)
        self._entered = entered
        self._release = release

    async def _on_start(self) -> None:
        await super()._on_start()
        self._entered.set()
        await self._release.wait()


class _MutatingPreviewMotor(SimulatedMotor):
    def __init__(self, identity: ResourceIdentity) -> None:
        super().__init__(identity)
        self.preview_calls = 0

    def preview_state(self) -> SimulationMotorPreviewState:
        state = super().preview_state()
        self.preview_calls += 1
        if self.preview_calls == 1:
            self.advance_time(0.0)
        return state


def _preview_resource(identity: str) -> SimulationPreviewResourceSnapshot:
    return SimulationPreviewResourceSnapshot(
        identity=ResourceIdentity(identity),
        kind="motor",
        lifecycle_state=LifecycleState.RUNNING,
        health_status=HealthStatus.HEALTHY,
        health_summary=None,
        state=SimulationMotorPreviewState(0.0, 0.0, 0.0, 0),
    )


def _simulated_runtime(
    *identities: str,
    event_sink: LocalEventRecorder | None = None,
) -> RuntimeManager:
    registry = ModelRegistry()
    register_simulated_motor(registry)
    resources = tuple((identity, SIMULATED_MOTOR_MODEL) for identity in identities)
    return RuntimeManager(_runtime_config(*resources), registry, event_sink=event_sink)


def _runtime_config(*resources: tuple[str, str]) -> RuntimeConfig:
    return RuntimeConfig(
        schema_version="1",
        resources=[
            ResourceDefinition(
                identity=ResourceIdentity(identity),
                model=model,
                settings={},
            )
            for identity, model in resources
        ],
    )
