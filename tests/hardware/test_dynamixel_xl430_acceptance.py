"""Explicitly opted-in physical acceptance for the fixed XL430 reference kit."""

from __future__ import annotations

import asyncio
import os
from contextlib import suppress
from pathlib import Path

import grpc
import pytest

from hiyelx.config import load_config
from hiyelx.drivers.dynamixel import register_dynamixel_xl430_motor
from hiyelx.models import ModelRegistry
from hiyelx.rpc import MotorGrpcServer, RpcTransportState
from hiyelx.rpc.generated import motor_pb2, motor_pb2_grpc
from hiyelx.runtime import RuntimeManager, RuntimeManagerState

pytestmark = pytest.mark.hardware
MOVEMENT_SECONDS = 0.25


def _require_physical_opt_in(pytestconfig: pytest.Config) -> str:
    marker_expression = pytestconfig.getoption("markexpr")
    if marker_expression != "hardware":
        pytest.skip("physical test requires the explicit '-m hardware' selection")
    if os.environ.get("HIYELX_RUN_HARDWARE") != "1":
        pytest.skip("set HIYELX_RUN_HARDWARE=1 to authorize physical motion")
    if os.environ.get("HIYELX_HARDWARE_SECURED_NO_LOAD") != "1":
        pytest.skip("confirm a secured, unloaded actuator and accessible power cutoff")
    device = os.environ.get("HIYELX_DYNAMIXEL_DEVICE", "")
    if not device.strip():
        pytest.skip("set HIYELX_DYNAMIXEL_DEVICE to the external serial-device path")
    return device


@pytest.mark.asyncio
async def test_physical_xl430_through_runtime_and_grpc(
    pytestconfig: pytest.Config,
    tmp_path: Path,
) -> None:
    """Run the bounded real-motor acceptance path only after explicit consent."""
    device = _require_physical_opt_in(pytestconfig)
    config_path = tmp_path / "physical-xl430.yaml"
    config_path.write_text(
        f"""\
schema_version: "1"
resources:
  - identity: reference_motor
    model: motor.dynamixel.xl430_w250_t
    settings:
      device: {device!r}
      motor_id: 1
      baud_rate: 57600
      max_abs_velocity_rad_s: 0.3
""",
        encoding="utf-8",
    )

    registry = ModelRegistry()
    register_dynamixel_xl430_motor(registry)
    runtime = RuntimeManager(load_config(config_path), registry)
    server = MotorGrpcServer(runtime)
    channel: grpc.aio.Channel | None = None
    client: motor_pb2_grpc.MotorServiceStub | None = None

    try:
        await runtime.start()
        await server.start_transport()
        channel = grpc.aio.insecure_channel(server.target)
        client = motor_pb2_grpc.MotorServiceStub(channel)

        listing = await client.ListMotors(motor_pb2.ListMotorsRequest())
        assert [motor.identity for motor in listing.motors] == ["reference_motor"]
        await client.GetMotorState(motor_pb2.GetMotorStateRequest(identity="reference_motor"))

        for velocity in (0.3, -0.3):
            await client.ApplyMotorCommand(
                motor_pb2.ApplyMotorCommandRequest(
                    identity="reference_motor",
                    angular_velocity_radians_per_second=velocity,
                )
            )
            await asyncio.sleep(MOVEMENT_SECONDS)
            await client.StopMotor(motor_pb2.StopMotorRequest(identity="reference_motor"))
            state = await client.GetMotorState(
                motor_pb2.GetMotorStateRequest(identity="reference_motor")
            )
            assert state.state.identity == "reference_motor"
    finally:
        if client is not None:
            with suppress(Exception):
                await client.StopMotor(motor_pb2.StopMotorRequest(identity="reference_motor"))
        if channel is not None:
            with suppress(Exception):
                await channel.close()
        if server.state is RpcTransportState.RUNNING:
            with suppress(Exception):
                await server.stop_transport()
        if runtime.state is RuntimeManagerState.RUNNING:
            with suppress(Exception):
                await runtime.shutdown()

    assert runtime.state is RuntimeManagerState.STOPPED
    assert server.state is RpcTransportState.STOPPED
