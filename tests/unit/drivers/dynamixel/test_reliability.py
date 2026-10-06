import asyncio

import pytest

from hiyelx.components import MotorCommand
from hiyelx.drivers.dynamixel import (
    VelocityWriteError,
    XL430Motor,
    XL430MotorSettings,
)
from hiyelx.drivers.dynamixel.transport import TransportCommunicationError
from hiyelx.resources import (
    HealthStatus,
    LifecycleState,
    OperationDeadlineExceeded,
    OperationDeadlinePolicy,
    ResourceIdentity,
    ResourceStartupError,
)
from tests.unit.drivers.dynamixel.fake_transport import FakeDynamixelTransport


def _motor(
    transport: FakeDynamixelTransport,
    *,
    startup: float = 1.0,
    shutdown: float = 1.0,
    command: float = 1.0,
    state_read: float = 1.0,
    transport_operation: float = 0.01,
) -> XL430Motor:
    return XL430Motor(
        ResourceIdentity("reference_motor"),
        XL430MotorSettings(device="/dev/reference"),
        transport,
        deadline_policy=OperationDeadlinePolicy(
            startup_seconds=startup,
            shutdown_seconds=shutdown,
            motor_command_seconds=command,
            motor_state_read_seconds=state_read,
            transport_operation_seconds=transport_operation,
        ),
    )


async def _wait_for_block(transport: FakeDynamixelTransport) -> None:
    entered = await asyncio.wait_for(
        asyncio.to_thread(transport.block_entered.wait, 1.0),
        timeout=1.1,
    )
    assert entered


@pytest.mark.asyncio
async def test_startup_timeout_stays_failed_after_late_backend_completion() -> None:
    transport = FakeDynamixelTransport()
    transport.blocked_key = "open_port"
    motor = _motor(transport, startup=0.03, transport_operation=0.01)

    start_task = asyncio.create_task(motor.start())
    await _wait_for_block(transport)
    with pytest.raises(ResourceStartupError) as caught:
        await start_task

    assert isinstance(caught.value.__cause__, OperationDeadlineExceeded)
    assert motor.state is LifecycleState.FAILED
    assert motor.health.status is HealthStatus.UNHEALTHY

    transport.block_release.set()
    completed = await asyncio.to_thread(transport.block_completed.wait, 1.0)
    assert completed
    await asyncio.sleep(0)

    assert motor.state is LifecycleState.FAILED
    assert motor.health.status is HealthStatus.UNHEALTHY


@pytest.mark.asyncio
async def test_late_command_completion_cannot_race_shutdown_or_restore_health() -> None:
    transport = FakeDynamixelTransport()
    motor = _motor(transport, shutdown=1.0)
    await motor.start()
    transport.events.clear()
    transport.max_concurrent_calls = 0
    transport.blocked_key = "write:104"

    command_task = asyncio.create_task(motor.apply_command(MotorCommand(0.1)))
    await _wait_for_block(transport)
    with pytest.raises(OperationDeadlineExceeded) as caught:
        await command_task

    assert caught.value.operation == "write_goal_velocity"
    assert motor.state is LifecycleState.RUNNING
    assert motor.health.status is HealthStatus.UNHEALTHY

    shutdown_task = asyncio.create_task(motor.shutdown())
    await asyncio.sleep(0)
    assert transport.max_concurrent_calls == 1
    transport.blocked_key = None
    transport.block_release.set()
    await shutdown_task

    assert transport.max_concurrent_calls == 1
    assert motor.state is LifecycleState.STOPPED
    assert motor.health.status is HealthStatus.UNHEALTHY


@pytest.mark.asyncio
async def test_communication_failure_is_chained_and_visible_in_health() -> None:
    transport = FakeDynamixelTransport()
    motor = _motor(transport)
    await motor.start()
    failure = TransportCommunicationError("write", -1001, 104)
    transport.fail_next("write:104", failure)

    with pytest.raises(VelocityWriteError) as caught:
        await motor.apply_command(MotorCommand(0.1))

    assert caught.value.__cause__ is failure
    assert motor.state is LifecycleState.RUNNING
    assert motor.health.status is HealthStatus.UNHEALTHY
    assert motor.health.detail == "backend unavailable during motor command"
    assert "-1001" not in (motor.health.detail or "")
