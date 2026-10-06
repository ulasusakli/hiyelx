import asyncio

import pytest

from hiyelx.components import Motor, MotorCommand, MotorState
from hiyelx.resources import (
    HealthStatus,
    LifecycleState,
    OperationDeadlineExceeded,
    OperationDeadlinePolicy,
    ResourceIdentity,
)
from hiyelx.simulation import SimulatedMotor


class ControlledMotor(Motor):
    def __init__(self, identity: ResourceIdentity) -> None:
        super().__init__(
            identity,
            deadline_policy=OperationDeadlinePolicy(
                startup_seconds=1.0,
                shutdown_seconds=1.0,
                motor_command_seconds=0.01,
                motor_state_read_seconds=0.01,
                transport_operation_seconds=1.0,
            ),
        )
        self.command_gate = asyncio.Event()
        self.read_gate = asyncio.Event()

    async def _apply_command(self, command: MotorCommand) -> None:
        del command
        await self.command_gate.wait()

    async def _read_state(self) -> MotorState:
        await self.read_gate.wait()
        return MotorState(0.0, 0.0)


@pytest.mark.asyncio
async def test_motor_command_deadline_is_typed_and_visible_in_health() -> None:
    motor = ControlledMotor(ResourceIdentity("slow-command"))
    await motor.start()

    with pytest.raises(OperationDeadlineExceeded) as caught:
        await motor.apply_command(MotorCommand(0.2))

    assert caught.value.operation == "motor_command"
    assert caught.value.lifecycle_state is LifecycleState.RUNNING
    assert motor.state is LifecycleState.RUNNING
    assert motor.health.status is HealthStatus.UNHEALTHY
    assert motor.health.detail == "deadline exceeded during motor command"


@pytest.mark.asyncio
async def test_motor_state_read_deadline_is_typed_and_visible_in_health() -> None:
    motor = ControlledMotor(ResourceIdentity("slow-read"))
    await motor.start()

    with pytest.raises(OperationDeadlineExceeded) as caught:
        await motor.read_state()

    assert caught.value.operation == "motor_state_read"
    assert caught.value.lifecycle_state is LifecycleState.RUNNING
    assert motor.state is LifecycleState.RUNNING
    assert motor.health.status is HealthStatus.UNHEALTHY
    assert motor.health.detail == "deadline exceeded during motor state read"


@pytest.mark.asyncio
async def test_simulation_retains_motor_contract_with_deadline_policy() -> None:
    motor = SimulatedMotor(
        ResourceIdentity("simulated"),
        deadline_policy=OperationDeadlinePolicy(),
    )
    await motor.start()

    await motor.apply_command(MotorCommand(-0.25))
    motor.advance_time(2.0)

    assert await motor.read_state() == MotorState(-0.5, -0.25)
    assert motor.health.status is HealthStatus.HEALTHY
