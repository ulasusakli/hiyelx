from collections.abc import Awaitable
from pathlib import Path

import grpc
import pytest

from hiyelx.components import Motor, MotorCommand, MotorState
from hiyelx.config import ResourceDefinition, RuntimeConfig, load_config
from hiyelx.models import ModelRegistry
from hiyelx.resources import Resource, ResourceIdentity
from hiyelx.rpc import MotorGrpcServer
from hiyelx.rpc.generated import motor_pb2, motor_pb2_grpc
from hiyelx.runtime import RuntimeManager, RuntimeManagerState
from hiyelx.simulation import SimulatedMotor, register_simulated_motor


class ExplodingMotor(Motor):
    async def _apply_command(self, command: MotorCommand) -> None:
        del command

    async def _read_state(self) -> MotorState:
        raise RuntimeError("secret /tmp/runtime-config.yaml")


def _register_plain_resource(registry: ModelRegistry) -> None:
    def create(definition: ResourceDefinition) -> Resource:
        return Resource(definition.identity)

    registry.register("test.resource", create)


async def _assert_rpc_error(
    call: Awaitable[object],
    expected_code: grpc.StatusCode,
    *,
    absent_detail: str | None = None,
) -> None:
    with pytest.raises(grpc.aio.AioRpcError) as caught:
        await call
    assert caught.value.code() is expected_code
    if absent_detail is not None:
        assert absent_detail not in (caught.value.details() or "")


@pytest.mark.asyncio
async def test_end_to_end_motor_control_over_real_loopback(
    tmp_path: Path,
) -> None:
    path = tmp_path / "runtime.yaml"
    path.write_text(
        """\
schema_version: "1"
resources:
  - identity: z_motor
    model: motor.simulated
    settings: {}
  - identity: helper
    model: test.resource
    settings: {}
  - identity: a_motor
    model: motor.simulated
    settings: {}
""",
        encoding="utf-8",
    )
    registry = ModelRegistry()
    register_simulated_motor(registry)
    _register_plain_resource(registry)
    runtime = RuntimeManager(load_config(path), registry)
    await runtime.start()
    server = MotorGrpcServer(runtime, port=0)
    await server.start_transport()
    channel = grpc.aio.insecure_channel(server.target)
    client = motor_pb2_grpc.MotorServiceStub(channel)

    try:
        listing = await client.ListMotors(motor_pb2.ListMotorsRequest())
        assert [motor.identity for motor in listing.motors] == ["a_motor", "z_motor"]
        assert all(
            motor.lifecycle_state == motor_pb2.RESOURCE_LIFECYCLE_STATE_RUNNING
            for motor in listing.motors
        )

        for velocity in (2.0, -1.5, 0.0):
            response = await client.ApplyMotorCommand(
                motor_pb2.ApplyMotorCommandRequest(
                    identity="z_motor",
                    angular_velocity_radians_per_second=velocity,
                )
            )
            assert response.state.identity == "z_motor"
            assert response.state.angular_velocity_radians_per_second == velocity

        await client.ApplyMotorCommand(
            motor_pb2.ApplyMotorCommandRequest(
                identity="z_motor",
                angular_velocity_radians_per_second=2.0,
            )
        )
        resource = runtime.get_resource(ResourceIdentity("z_motor"))
        assert isinstance(resource, SimulatedMotor)
        resource.advance_time(1.25)

        state = await client.GetMotorState(motor_pb2.GetMotorStateRequest(identity="z_motor"))
        assert state.state.identity == "z_motor"
        assert state.state.angular_position_radians == 2.5
        assert state.state.angular_velocity_radians_per_second == 2.0
        assert state.state.lifecycle_state == motor_pb2.RESOURCE_LIFECYCLE_STATE_RUNNING

        stopped = await client.StopMotor(motor_pb2.StopMotorRequest(identity="z_motor"))
        assert stopped.state.angular_velocity_radians_per_second == 0.0
    finally:
        await channel.close()
        await server.stop_transport()

    assert runtime.state is RuntimeManagerState.RUNNING
    await runtime.shutdown()


@pytest.mark.asyncio
async def test_invalid_identity_command_and_resource_failures_map_to_statuses() -> None:
    registry = ModelRegistry()
    register_simulated_motor(registry)
    _register_plain_resource(registry)
    runtime = RuntimeManager(
        RuntimeConfig(
            schema_version="1",
            resources=[
                ResourceDefinition(
                    identity=ResourceIdentity("motor"),
                    model="motor.simulated",
                    settings={},
                ),
                ResourceDefinition(
                    identity=ResourceIdentity("plain"),
                    model="test.resource",
                    settings={},
                ),
            ],
        ),
        registry,
    )
    await runtime.start()
    server = MotorGrpcServer(runtime)
    await server.start_transport()
    channel = grpc.aio.insecure_channel(server.target)
    client = motor_pb2_grpc.MotorServiceStub(channel)
    try:
        await _assert_rpc_error(
            client.GetMotorState(motor_pb2.GetMotorStateRequest(identity=" ")),
            grpc.StatusCode.INVALID_ARGUMENT,
        )
        for value in (float("nan"), float("inf"), float("-inf")):
            await _assert_rpc_error(
                client.ApplyMotorCommand(
                    motor_pb2.ApplyMotorCommandRequest(
                        identity="motor",
                        angular_velocity_radians_per_second=value,
                    )
                ),
                grpc.StatusCode.INVALID_ARGUMENT,
            )
        await _assert_rpc_error(
            client.GetMotorState(motor_pb2.GetMotorStateRequest(identity="missing")),
            grpc.StatusCode.NOT_FOUND,
        )
        await _assert_rpc_error(
            client.GetMotorState(motor_pb2.GetMotorStateRequest(identity="plain")),
            grpc.StatusCode.FAILED_PRECONDITION,
        )
    finally:
        await channel.close()
        await server.stop_transport()
        await runtime.shutdown()


@pytest.mark.asyncio
async def test_motor_lifecycle_rejection_maps_to_failed_precondition() -> None:
    registry = ModelRegistry()
    register_simulated_motor(registry)
    config = RuntimeConfig(
        schema_version="1",
        resources=[
            ResourceDefinition(
                identity=ResourceIdentity("motor"),
                model="motor.simulated",
                settings={},
            )
        ],
    )
    runtime = RuntimeManager(config, registry)
    await runtime.start()
    motor = runtime.get_resource(ResourceIdentity("motor"))
    await motor.shutdown()
    server = MotorGrpcServer(runtime)
    await server.start_transport()
    channel = grpc.aio.insecure_channel(server.target)
    client = motor_pb2_grpc.MotorServiceStub(channel)
    try:
        await _assert_rpc_error(
            client.StopMotor(motor_pb2.StopMotorRequest(identity="motor")),
            grpc.StatusCode.FAILED_PRECONDITION,
        )
    finally:
        await channel.close()
        await server.stop_transport()


@pytest.mark.asyncio
async def test_non_running_runtime_maps_to_unavailable() -> None:
    runtime = RuntimeManager(RuntimeConfig(schema_version="1", resources=[]), ModelRegistry())
    server = MotorGrpcServer(runtime)
    await server.start_transport()
    channel = grpc.aio.insecure_channel(server.target)
    client = motor_pb2_grpc.MotorServiceStub(channel)
    try:
        await _assert_rpc_error(
            client.ListMotors(motor_pb2.ListMotorsRequest()),
            grpc.StatusCode.UNAVAILABLE,
        )
    finally:
        await channel.close()
        await server.stop_transport()
    assert runtime.state is RuntimeManagerState.NEW


@pytest.mark.asyncio
async def test_unexpected_failure_maps_to_concealed_internal_status() -> None:
    registry = ModelRegistry()

    def create(definition: ResourceDefinition) -> Resource:
        return ExplodingMotor(definition.identity)

    registry.register("test.exploding", create)
    runtime = RuntimeManager(
        RuntimeConfig(
            schema_version="1",
            resources=[
                ResourceDefinition(
                    identity=ResourceIdentity("motor"),
                    model="test.exploding",
                    settings={},
                )
            ],
        ),
        registry,
    )
    await runtime.start()
    server = MotorGrpcServer(runtime)
    await server.start_transport()
    channel = grpc.aio.insecure_channel(server.target)
    client = motor_pb2_grpc.MotorServiceStub(channel)
    try:
        await _assert_rpc_error(
            client.GetMotorState(motor_pb2.GetMotorStateRequest(identity="motor")),
            grpc.StatusCode.INTERNAL,
            absent_detail="secret",
        )
    finally:
        await channel.close()
        await server.stop_transport()
        await runtime.shutdown()
