from dataclasses import FrozenInstanceError

import pytest

from hiyelx.components import (
    InvalidMotorCommandError,
    InvalidMotorStateError,
    MotorCommand,
    MotorState,
)


def test_motor_command_is_immutable() -> None:
    command = MotorCommand(angular_velocity_radians_per_second=1.5)
    field = "angular_velocity_radians_per_second"

    with pytest.raises(FrozenInstanceError):
        setattr(command, field, 2.0)


def test_motor_state_is_immutable() -> None:
    state = MotorState(
        angular_position_radians=1.0,
        angular_velocity_radians_per_second=-2.0,
    )
    field = "angular_position_radians"

    with pytest.raises(FrozenInstanceError):
        setattr(state, field, 3.0)


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_motor_command_rejects_non_finite_velocity(value: float) -> None:
    with pytest.raises(InvalidMotorCommandError) as caught:
        MotorCommand(angular_velocity_radians_per_second=value)

    assert caught.value.angular_velocity_radians_per_second == value or value != value


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_motor_state_rejects_non_finite_values(value: float) -> None:
    with pytest.raises(InvalidMotorStateError):
        MotorState(
            angular_position_radians=value,
            angular_velocity_radians_per_second=0.0,
        )


def test_zero_velocity_command_has_exact_zero_velocity() -> None:
    assert MotorCommand.zero_velocity() == MotorCommand(
        angular_velocity_radians_per_second=0.0
    )
