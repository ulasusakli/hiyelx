import sys
from dataclasses import FrozenInstanceError

import pytest

from hiyelx.components import MotorCommand, MotorState, MotorUnavailableError
from hiyelx.resources import LifecycleState, ResourceIdentity
from hiyelx.simulation import (
    InvalidSimulationPreviewStateError,
    InvalidSimulationTimeStep,
    SimulatedMotor,
    SimulationMotorPreviewState,
)


@pytest.mark.asyncio
async def test_initial_simulated_state_is_zero() -> None:
    motor = SimulatedMotor(ResourceIdentity("motor/initial"))

    assert await motor.read_state() == MotorState(
        angular_position_radians=0.0,
        angular_velocity_radians_per_second=0.0,
    )
    assert motor.preview_state() == SimulationMotorPreviewState(0.0, 0.0, 0.0, 0)


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
    before_startup_preview = motor.preview_state()

    with pytest.raises(MotorUnavailableError) as before_startup:
        await motor.apply_command(command)
    assert before_startup.value.lifecycle_state is LifecycleState.CREATED
    assert motor.preview_state() == before_startup_preview

    await motor.start()
    await motor.shutdown()
    after_shutdown_preview = motor.preview_state()

    with pytest.raises(MotorUnavailableError) as after_shutdown:
        await motor.stop()
    assert after_shutdown.value.lifecycle_state is LifecycleState.STOPPED
    assert motor.preview_state() == after_shutdown_preview


@pytest.mark.asyncio
async def test_apply_and_read_velocity_command() -> None:
    motor = await _running_motor("motor/velocity")

    await motor.apply_command(MotorCommand(-2.5))

    assert await motor.read_state() == MotorState(0.0, -2.5)


@pytest.mark.asyncio
async def test_integer_velocity_command_is_normalized_for_preview() -> None:
    motor = await _running_motor("motor/integer-velocity")

    await motor.apply_command(MotorCommand(1))

    state = await motor.read_state()
    preview = motor.preview_state()
    assert type(state.angular_velocity_radians_per_second) is float
    assert type(preview.angular_velocity_radians_per_second) is float
    assert preview == SimulationMotorPreviewState(0.0, 1.0, 0.0, 1)


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
    assert motor.preview_state() == SimulationMotorPreviewState(
        angular_position_radians=3.0,
        angular_velocity_radians_per_second=-1.0,
        simulation_time_seconds=3.25,
        revision=5,
    )


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
    preview_before = motor.preview_state()

    with pytest.raises(InvalidSimulationTimeStep) as caught:
        motor.advance_time(time_step_seconds)

    assert (
        caught.value.time_step_seconds == time_step_seconds
        or time_step_seconds != time_step_seconds
    )
    assert await motor.read_state() == state_before
    assert motor.preview_state() == preview_before


@pytest.mark.asyncio
async def test_time_advancement_requires_running_lifecycle() -> None:
    motor = SimulatedMotor(ResourceIdentity("motor/time-unavailable"))
    preview_before = motor.preview_state()

    with pytest.raises(MotorUnavailableError):
        motor.advance_time(1.0)

    assert motor.preview_state() == preview_before


@pytest.mark.asyncio
async def test_shutdown_forces_zero_velocity_and_preserves_position() -> None:
    motor = await _running_motor("motor/shutdown")
    await motor.apply_command(MotorCommand(2.0))
    motor.advance_time(1.25)

    await motor.shutdown()

    assert await motor.read_state() == MotorState(2.5, 0.0)
    assert motor.preview_state() == SimulationMotorPreviewState(2.5, 0.0, 1.25, 3)


@pytest.mark.asyncio
async def test_zero_time_step_is_a_deterministic_mutation() -> None:
    motor = await _running_motor("motor/zero-step")
    before = motor.preview_state()

    motor.advance_time(0.0)

    assert motor.preview_state() == SimulationMotorPreviewState(
        angular_position_radians=before.angular_position_radians,
        angular_velocity_radians_per_second=before.angular_velocity_radians_per_second,
        simulation_time_seconds=before.simulation_time_seconds,
        revision=before.revision + 1,
    )


@pytest.mark.asyncio
async def test_accumulated_time_overflow_is_rejected_without_mutation() -> None:
    motor = await _running_motor("motor/time-overflow")
    motor.advance_time(sys.float_info.max)
    before = motor.preview_state()

    with pytest.raises(InvalidSimulationTimeStep):
        motor.advance_time(sys.float_info.max)

    assert motor.preview_state() == before


@pytest.mark.asyncio
async def test_command_stop_and_preview_reads_have_exact_revision_semantics() -> None:
    motor = await _running_motor("motor/revision")

    first_read = motor.preview_state()
    second_read = motor.preview_state()
    assert first_read == second_read == SimulationMotorPreviewState(0.0, 0.0, 0.0, 0)

    await motor.apply_command(MotorCommand(2.0))
    assert motor.preview_state() == SimulationMotorPreviewState(0.0, 2.0, 0.0, 1)

    motor.advance_time(1.5)
    assert motor.preview_state() == SimulationMotorPreviewState(3.0, 2.0, 1.5, 2)

    await motor.stop()
    assert motor.preview_state() == SimulationMotorPreviewState(3.0, 0.0, 1.5, 3)


def test_preview_state_is_frozen_and_strictly_validated() -> None:
    state = SimulationMotorPreviewState(0.0, 0.0, 0.0, 0)

    with pytest.raises(FrozenInstanceError):
        state.revision = 1  # type: ignore[misc]

    with pytest.raises(InvalidSimulationPreviewStateError) as revision_error:
        SimulationMotorPreviewState(0.0, 0.0, 0.0, 1.0)  # type: ignore[arg-type]
    assert revision_error.value.field == "revision"


@pytest.mark.parametrize(
    ("field", "values"),
    [
        ("angular_position_radians", (0, 0.0, 0.0, 0)),
        ("angular_position_radians", (True, 0.0, 0.0, 0)),
        ("angular_position_radians", (float("nan"), 0.0, 0.0, 0)),
        ("angular_velocity_radians_per_second", (0.0, 0, 0.0, 0)),
        ("angular_velocity_radians_per_second", (0.0, float("inf"), 0.0, 0)),
        ("simulation_time_seconds", (0.0, 0.0, False, 0)),
        ("simulation_time_seconds", (0.0, 0.0, -0.1, 0)),
        ("simulation_time_seconds", (0.0, 0.0, float("inf"), 0)),
        ("revision", (0.0, 0.0, 0.0, -1)),
        ("revision", (0.0, 0.0, 0.0, True)),
    ],
)
def test_invalid_preview_state_is_rejected(
    field: str,
    values: tuple[float, float, float, int],
) -> None:
    with pytest.raises(InvalidSimulationPreviewStateError) as caught:
        SimulationMotorPreviewState(*values)

    assert caught.value.field == field


async def _running_motor(identity: str) -> SimulatedMotor:
    motor = SimulatedMotor(ResourceIdentity(identity))
    await motor.start()
    return motor
