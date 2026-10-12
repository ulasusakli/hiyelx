"""Explicitly opted-in physical acceptance for the fixed XL430 reference kit."""

from __future__ import annotations

import asyncio
import os
from contextlib import suppress
from pathlib import Path

import grpc
import pytest

from hiyelx.acceptance import (
    PHYSICAL_OPERATION_CONSENT,
    XL430_W250_T_ACCEPTANCE_PROFILE,
    HardwareAcceptanceConfig,
    HardwareAcceptanceError,
    load_hardware_acceptance_config,
    preflight_hardware_acceptance,
)
from hiyelx.config import RuntimeConfig
from hiyelx.drivers.dynamixel import register_dynamixel_xl430_motor
from hiyelx.models import ModelRegistry
from hiyelx.rpc import MotorGrpcServer, RpcTransportState
from hiyelx.rpc.generated import motor_pb2, motor_pb2_grpc
from hiyelx.runtime import RuntimeManager, RuntimeManagerState

pytestmark = pytest.mark.hardware
MOVEMENT_SECONDS = 0.25


def _require_physical_opt_in(
    pytestconfig: pytest.Config,
) -> tuple[HardwareAcceptanceConfig, ModelRegistry]:
    marker_expression = pytestconfig.getoption("markexpr")
    if marker_expression != "hardware":
        pytest.skip("physical test requires the explicit '-m hardware' selection")
    consent = os.environ.get("HIYELX_PHYSICAL_OPERATION_CONSENT")
    if consent != PHYSICAL_OPERATION_CONSENT:
        pytest.skip("set the exact physical-operation consent value")
    if os.environ.get("HIYELX_HARDWARE_SECURED_NO_LOAD") != "1":
        pytest.skip("confirm a secured, unloaded actuator and accessible power cutoff")
    config_value = os.environ.get("HIYELX_HARDWARE_ACCEPTANCE_CONFIG", "")
    if not config_value.strip():
        pytest.skip("set the external hardware-acceptance configuration path")
    try:
        config = load_hardware_acceptance_config(Path(config_value))
        registry = ModelRegistry()
        register_dynamixel_xl430_motor(registry)
        plan = preflight_hardware_acceptance(
            config,
            registry,
            XL430_W250_T_ACCEPTANCE_PROFILE,
            physical_operation_consent=consent,
        )
    except HardwareAcceptanceError:
        pytest.fail("hardware acceptance preflight failed", pytrace=False)
    if not plan.physical_operation_authorized:
        pytest.skip("acceptance configuration does not authorize movement")
    return config, registry


@pytest.mark.asyncio
async def test_physical_xl430_through_runtime_and_grpc(
    pytestconfig: pytest.Config,
) -> None:
    """Run the bounded real-motor acceptance path only after explicit consent."""
    acceptance, registry = _require_physical_opt_in(pytestconfig)
    maximum_velocity = max(
        abs(acceptance.command_bounds.minimum_rad_s),
        abs(acceptance.command_bounds.maximum_rad_s),
    )
    runtime_config = RuntimeConfig.model_validate(
        {
            "schema_version": "1",
            "resources": [
                {
                    "identity": "reference_motor",
                    "model": acceptance.driver_identity,
                    "settings": {
                        "device": acceptance.transport_identifier,
                        "motor_id": acceptance.device_id,
                        "baud_rate": acceptance.baud_rate,
                        "max_abs_velocity_rad_s": maximum_velocity,
                    },
                }
            ],
        },
        strict=True,
    )
    runtime = RuntimeManager(runtime_config, registry)
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

        for velocity in (
            acceptance.command_bounds.maximum_rad_s,
            acceptance.command_bounds.minimum_rad_s,
        ):
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
