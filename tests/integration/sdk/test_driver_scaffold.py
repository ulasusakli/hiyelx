import importlib
import sys
from pathlib import Path
from types import ModuleType
from typing import Protocol, cast

import grpc
import pytest

from hiyelx.config import load_config
from hiyelx.models import ModelRegistry
from hiyelx.rpc import MotorGrpcServer, RpcTransportState
from hiyelx.rpc.generated import motor_pb2, motor_pb2_grpc
from hiyelx.runtime import RuntimeManager, RuntimeManagerState
from hiyelx.sdk import create_motor_driver_scaffold


class GeneratedDriverModule(Protocol):
    MODEL_NAME: str

    def register_acme_motor_driver(self, registry: ModelRegistry) -> None: ...


@pytest.mark.asyncio
async def test_generated_scaffold_runs_through_runtime_and_grpc(
    tmp_path: Path,
) -> None:
    output = tmp_path / "generated"
    create_motor_driver_scaffold(
        output,
        package_name="acme_motor_driver",
        model_name="motor.acme.reference",
    )
    output_value = str(output)
    sys.path.insert(0, output_value)
    try:
        imported: ModuleType = importlib.import_module("acme_motor_driver")
        driver_module = cast(GeneratedDriverModule, imported)
        registry = ModelRegistry()
        driver_module.register_acme_motor_driver(registry)
        runtime = RuntimeManager(load_config(output / "runtime.yaml"), registry)
        server = MotorGrpcServer(runtime)
        channel: grpc.aio.Channel | None = None

        try:
            await runtime.start()
            await server.start_transport()
            channel = grpc.aio.insecure_channel(server.target)
            client = motor_pb2_grpc.MotorServiceStub(channel)

            listing = await client.ListMotors(motor_pb2.ListMotorsRequest())
            assert [motor.identity for motor in listing.motors] == ["example_motor"]

            commanded = await client.ApplyMotorCommand(
                motor_pb2.ApplyMotorCommandRequest(
                    identity="example_motor",
                    angular_velocity_radians_per_second=0.25,
                )
            )
            assert commanded.state.angular_velocity_radians_per_second == 0.25

            stopped = await client.StopMotor(
                motor_pb2.StopMotorRequest(identity="example_motor")
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
    finally:
        sys.modules.pop("acme_motor_driver.acme_motor_driver", None)
        sys.modules.pop("acme_motor_driver", None)
        sys.path.remove(output_value)
