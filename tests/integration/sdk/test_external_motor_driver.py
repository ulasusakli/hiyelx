from pathlib import Path

import grpc
import pytest
from pydantic import BaseModel, ConfigDict

from hiyelx.components import Motor, MotorCommand, MotorState
from hiyelx.config import load_config
from hiyelx.models import ModelRegistry
from hiyelx.resources import ResourceIdentity
from hiyelx.rpc import MotorGrpcServer, RpcTransportState
from hiyelx.rpc.generated import motor_pb2, motor_pb2_grpc
from hiyelx.runtime import RuntimeManager, RuntimeManagerState
from hiyelx.sdk import register_motor_driver

EXTERNAL_MOTOR_MODEL = "motor.example.external"


class ExternalMotorSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    initial_position_radians: float


class ExternalMotor(Motor):
    def __init__(self, identity: ResourceIdentity, settings: ExternalMotorSettings) -> None:
        super().__init__(identity)
        self._motor_state = MotorState(settings.initial_position_radians, 0.0)

    async def _apply_command(self, command: MotorCommand) -> None:
        self._motor_state = MotorState(
            self._motor_state.angular_position_radians,
            command.angular_velocity_radians_per_second,
        )

    async def _read_state(self) -> MotorState:
        return self._motor_state


@pytest.mark.asyncio
async def test_external_motor_runs_through_config_runtime_and_grpc(
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "external-motor.yaml"
    config_path.write_text(
        """\
schema_version: "1"
resources:
  - identity: external_motor
    model: motor.example.external
    settings:
      initial_position_radians: 1.25
""",
        encoding="utf-8",
    )
    registry = ModelRegistry()
    register_motor_driver(
        registry,
        model_name=EXTERNAL_MOTOR_MODEL,
        settings_type=ExternalMotorSettings,
        builder=ExternalMotor,
    )
    runtime = RuntimeManager(load_config(config_path), registry)
    server = MotorGrpcServer(runtime)
    channel: grpc.aio.Channel | None = None

    try:
        await runtime.start()
        await server.start_transport()
        channel = grpc.aio.insecure_channel(server.target)
        client = motor_pb2_grpc.MotorServiceStub(channel)

        listing = await client.ListMotors(motor_pb2.ListMotorsRequest())
        assert [motor.identity for motor in listing.motors] == ["external_motor"]

        initial = await client.GetMotorState(
            motor_pb2.GetMotorStateRequest(identity="external_motor")
        )
        assert initial.state.angular_position_radians == 1.25
        assert initial.state.angular_velocity_radians_per_second == 0.0

        commanded = await client.ApplyMotorCommand(
            motor_pb2.ApplyMotorCommandRequest(
                identity="external_motor",
                angular_velocity_radians_per_second=-0.5,
            )
        )
        assert commanded.state.angular_velocity_radians_per_second == -0.5

        stopped = await client.StopMotor(
            motor_pb2.StopMotorRequest(identity="external_motor")
        )
        assert stopped.state.angular_velocity_radians_per_second == 0.0
    finally:
        if channel is not None:
            await channel.close()
        if server.state is RpcTransportState.RUNNING:
            await server.stop_transport()
        if runtime.state is RuntimeManagerState.RUNNING:
            await runtime.shutdown()

    assert runtime.state is RuntimeManagerState.STOPPED
    assert server.state is RpcTransportState.STOPPED
