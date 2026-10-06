from pathlib import Path

import grpc
import pytest

from hiyelx.config import load_config
from hiyelx.drivers.dynamixel import register_dynamixel_xl430_motor
from hiyelx.drivers.dynamixel.constants import (
    GOAL_VELOCITY_ADDRESS,
    PRESENT_POSITION_ADDRESS,
    PRESENT_VELOCITY_ADDRESS,
)
from hiyelx.drivers.dynamixel.conversion import (
    encode_signed_32,
    radians_per_second_to_raw,
)
from hiyelx.models import ModelRegistry
from hiyelx.rpc import MotorGrpcServer
from hiyelx.rpc.generated import motor_pb2, motor_pb2_grpc
from hiyelx.runtime import RuntimeManager, RuntimeManagerState
from tests.unit.drivers.dynamixel.fake_transport import FakeDynamixelTransport


@pytest.mark.asyncio
async def test_existing_runtime_and_grpc_path_controls_xl430_driver(
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "runtime.yaml"
    config_path.write_text(
        """\
schema_version: "1"
resources:
  - identity: reference_motor
    model: motor.dynamixel.xl430_w250_t
    settings:
      device: /dev/reference
      motor_id: 1
      baud_rate: 57600
      max_abs_velocity_rad_s: 0.5
""",
        encoding="utf-8",
    )
    transport = FakeDynamixelTransport()
    transport.registers[PRESENT_POSITION_ADDRESS] = encode_signed_32(25)
    transport.registers[PRESENT_VELOCITY_ADDRESS] = encode_signed_32(-2)
    registry = ModelRegistry()
    register_dynamixel_xl430_motor(registry, transport_factory=lambda _settings: transport)
    runtime = RuntimeManager(load_config(config_path), registry)
    await runtime.start()
    server = MotorGrpcServer(runtime)
    await server.start_transport()
    channel = grpc.aio.insecure_channel(server.target)
    client = motor_pb2_grpc.MotorServiceStub(channel)

    try:
        listing = await client.ListMotors(motor_pb2.ListMotorsRequest())
        assert [motor.identity for motor in listing.motors] == ["reference_motor"]

        await client.ApplyMotorCommand(
            motor_pb2.ApplyMotorCommandRequest(
                identity="reference_motor",
                angular_velocity_radians_per_second=-0.2,
            )
        )
        assert transport.registers[GOAL_VELOCITY_ADDRESS] == encode_signed_32(
            radians_per_second_to_raw(-0.2)
        )

        state = await client.GetMotorState(
            motor_pb2.GetMotorStateRequest(identity="reference_motor")
        )
        assert state.state.identity == "reference_motor"
        assert state.state.angular_position_radians > 0.0
        assert state.state.angular_velocity_radians_per_second < 0.0

        await client.StopMotor(motor_pb2.StopMotorRequest(identity="reference_motor"))
        assert transport.registers[GOAL_VELOCITY_ADDRESS] == 0
    finally:
        await channel.close()
        await server.stop_transport()
        await runtime.shutdown()

    assert runtime.state is RuntimeManagerState.STOPPED
