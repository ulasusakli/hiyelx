import pytest

from hiyelx.components import MotorCommand, MotorState, MotorUnavailableError
from hiyelx.resources import LifecycleState, ResourceIdentity
from hiyelx.simulation import InvalidSimulationTimeStep, SimulatedMotor


@pytest.mark.asyncio
async def test_initial_simulated_state_is_zero() -> None:
    motor = SimulatedMotor(ResourceIdentity("motor/initial"))

    assert await motor.read_state() == MotorState(
        angular_position_radians=0.0,
        angular_velocity_radians_per_second=0.0,
    )


@pytest.mark.asyncio
async def test_successful_startup_and_shutdown() -> None:
    motor = SimulatedMotor(ResourceIdentity("motor/lifecycle"))

    await motor.start()
    assert motor.state is LifecycleState.RUNNING
    assert await motor.read_state() == MotorState(0.0, 0.0)

    await motor.shutdown()
    assert motor.state is LifecycleState.STOPPED


@pytest.mark.asyncio
async def test_commands_are_rejected_before_startup_and_after_shutdown() -> None:
    motor = SimulatedMotor(ResourceIdentity("motor/unavailable"))
    command = MotorCommand(1.0)

    with pytest.raises(MotorUnavailableError) as before_startup:
        await motor.apply_command(command)
    assert before_startup.value.lifecycle_state is LifecycleState.CREATED

    await motor.start()
    await motor.shutdown()

    with pytest.raises(MotorUnavailableError) as after_shutdown:
        await motor.stop()
    assert after_shutdown.value.lifecycle_state is LifecycleState.STOPPED


@pytest.mark.asyncio
async def test_apply_and_read_velocity_command() -> None:
    motor = await _running_motor("motor/velocity")

    await motor.apply_command(MotorCommand(-2.5))

    assert await motor.read_state() == MotorState(0.0, -2.5)


@pytest.mark.asyncio
async def test_stop_commands_zero_velocity_without_changing_position() -> None:
    motor = await _running_motor("motor/stop")
    await motor.apply_command(MotorCommand(2.0))
    motor.advance_time(1.5)

    await motor.stop()

    assert await motor.read_state() == MotorState(3.0, 0.0)


@pytest.mark.asyncio
async def test_position_uses_piecewise_constant_velocity_integration() -> None:
    motor = await _running_motor("motor/integration")
    await motor.apply_command(MotorCommand(4.0))

    motor.advance_time(0.25)

    assert await motor.read_state() == MotorState(1.0, 4.0)


@pytest.mark.asyncio
async def test_multiple_time_steps_accumulate_position() -> None:
    motor = await _running_motor("motor/accumulation")
    await motor.apply_command(MotorCommand(1.5))

    motor.advance_time(2.0)
    motor.advance_time(0.5)
    await motor.apply_command(MotorCommand(-1.0))
    motor.advance_time(0.75)

    assert await motor.read_state() == MotorState(3.0, -1.0)


@pytest.mark.asyncio
async def test_equivalent_sequences_produce_equivalent_states() -> None:
    first = await _running_motor("motor/determinism/first")
    second = await _running_motor("motor/determinism/second")

    for motor in (first, second):
        await motor.apply_command(MotorCommand(2.0))
        motor.advance_time(0.5)
        await motor.apply_command(MotorCommand(-0.5))
        motor.advance_time(2.0)
        await motor.stop()
        motor.advance_time(10.0)

    assert await first.read_state() == await second.read_state()
    assert await first.read_state() == MotorState(0.0, 0.0)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "time_step_seconds",
    [-0.1, float("nan"), float("inf"), float("-inf")],
)
async def test_invalid_time_steps_are_rejected_without_changing_state(
    time_step_seconds: float,
) -> None:
    motor = await _running_motor("motor/invalid-step")
    await motor.apply_command(MotorCommand(3.0))
    state_before = await motor.read_state()

    with pytest.raises(InvalidSimulationTimeStep) as caught:
        motor.advance_time(time_step_seconds)

    assert (
        caught.value.time_step_seconds == time_step_seconds
        or time_step_seconds != time_step_seconds
    )
    assert await motor.read_state() == state_before


@pytest.mark.asyncio
async def test_time_advancement_requires_running_lifecycle() -> None:
    motor = SimulatedMotor(ResourceIdentity("motor/time-unavailable"))

    with pytest.raises(MotorUnavailableError):
        motor.advance_time(1.0)


@pytest.mark.asyncio
async def test_shutdown_forces_zero_velocity_and_preserves_position() -> None:
    motor = await _running_motor("motor/shutdown")
    await motor.apply_command(MotorCommand(2.0))
    motor.advance_time(1.25)

    await motor.shutdown()

    assert await motor.read_state() == MotorState(2.5, 0.0)


async def _running_motor(identity: str) -> SimulatedMotor:
    motor = SimulatedMotor(ResourceIdentity(identity))
    await motor.start()
    return motor
