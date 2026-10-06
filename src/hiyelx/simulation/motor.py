"""Deterministic simulated motor backend.

Simulation time advances only through ``advance_time``. Each step uses
piecewise-constant velocity integration::

    next_position = current_position + current_velocity * time_step_seconds

Commands take effect immediately without advancing time. No wall clock,
background task, randomness, or physical-dynamics model is involved.
"""

from math import isfinite

from hiyelx.components import Motor, MotorCommand, MotorState
from hiyelx.resources import (
    DEFAULT_OPERATION_DEADLINES,
    OperationDeadlinePolicy,
    ResourceIdentity,
)


class InvalidSimulationTimeStep(ValueError):
    """Raised when a simulated time step is negative or non-finite."""

    def __init__(self, time_step_seconds: float) -> None:
        self.time_step_seconds = time_step_seconds
        super().__init__("simulation time step must be finite and non-negative")


class SimulatedMotor(Motor):
    """A deterministic motor driven only by explicitly advanced time."""

    def __init__(
        self,
        identity: ResourceIdentity,
        *,
        deadline_policy: OperationDeadlinePolicy = DEFAULT_OPERATION_DEADLINES,
    ) -> None:
        super().__init__(identity, deadline_policy=deadline_policy)
        self._motor_state = MotorState(
            angular_position_radians=0.0,
            angular_velocity_radians_per_second=0.0,
        )

    def advance_time(self, time_step_seconds: float) -> None:
        """Advance simulation by a finite, non-negative number of seconds."""
        if not isfinite(time_step_seconds) or time_step_seconds < 0.0:
            raise InvalidSimulationTimeStep(time_step_seconds)
        self._require_running()
        self._motor_state = MotorState(
            angular_position_radians=(
                self._motor_state.angular_position_radians
                + self._motor_state.angular_velocity_radians_per_second
                * time_step_seconds
            ),
            angular_velocity_radians_per_second=(
                self._motor_state.angular_velocity_radians_per_second
            ),
        )

    async def _on_start(self) -> None:
        self._motor_state = MotorState(
            angular_position_radians=0.0,
            angular_velocity_radians_per_second=0.0,
        )

    async def _on_shutdown(self) -> None:
        self._motor_state = MotorState(
            angular_position_radians=self._motor_state.angular_position_radians,
            angular_velocity_radians_per_second=0.0,
        )

    async def _apply_command(self, command: MotorCommand) -> None:
        self._motor_state = MotorState(
            angular_position_radians=self._motor_state.angular_position_radians,
            angular_velocity_radians_per_second=(
                command.angular_velocity_radians_per_second
            ),
        )

    async def _read_state(self) -> MotorState:
        return self._motor_state
