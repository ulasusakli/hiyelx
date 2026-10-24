"""Deterministic simulated motor backend.

Simulation time advances only through ``advance_time``. Each step uses
piecewise-constant velocity integration::

    next_position = current_position + current_velocity * time_step_seconds

Commands take effect immediately without advancing time. A monotonic revision
records every successful state mutation, including a zero-second time step.
No wall clock, background task, randomness, or physical-dynamics model is
involved.
"""

from dataclasses import dataclass
from math import isfinite
from threading import RLock

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


class InvalidSimulationPreviewStateError(ValueError):
    """Raised when simulation preview state violates its frozen contract."""

    def __init__(self, field: str) -> None:
        self.field = field
        super().__init__(f"simulation preview {field} is invalid")


@dataclass(frozen=True, slots=True)
class SimulationMotorPreviewState:
    """Immutable deterministic motor state for renderer-neutral preview."""

    angular_position_radians: float
    angular_velocity_radians_per_second: float
    simulation_time_seconds: float
    revision: int

    def __post_init__(self) -> None:
        finite_values = (
            ("angular_position_radians", self.angular_position_radians),
            (
                "angular_velocity_radians_per_second",
                self.angular_velocity_radians_per_second,
            ),
            ("simulation_time_seconds", self.simulation_time_seconds),
        )
        for field, value in finite_values:
            if type(value) is not float or not isfinite(value):
                raise InvalidSimulationPreviewStateError(field)
        if self.simulation_time_seconds < 0.0:
            raise InvalidSimulationPreviewStateError("simulation_time_seconds")
        if type(self.revision) is not int or self.revision < 0:
            raise InvalidSimulationPreviewStateError("revision")


class SimulatedMotor(Motor):
    """A deterministic motor driven only by explicitly advanced time."""

    def __init__(
        self,
        identity: ResourceIdentity,
        *,
        deadline_policy: OperationDeadlinePolicy = DEFAULT_OPERATION_DEADLINES,
    ) -> None:
        super().__init__(identity, deadline_policy=deadline_policy)
        self._preview_lock = RLock()
        self._motor_state = MotorState(
            angular_position_radians=0.0,
            angular_velocity_radians_per_second=0.0,
        )
        self._simulation_time_seconds = 0.0
        self._revision = 0

    def advance_time(self, time_step_seconds: float) -> None:
        """Advance simulation by a finite, non-negative number of seconds."""
        if not isfinite(time_step_seconds) or time_step_seconds < 0.0:
            raise InvalidSimulationTimeStep(time_step_seconds)
        with self._preview_lock:
            self._require_running()
            next_simulation_time = self._simulation_time_seconds + time_step_seconds
            if not isfinite(next_simulation_time):
                raise InvalidSimulationTimeStep(time_step_seconds)
            next_motor_state = MotorState(
                angular_position_radians=(
                    self._motor_state.angular_position_radians
                    + self._motor_state.angular_velocity_radians_per_second
                    * time_step_seconds
                ),
                angular_velocity_radians_per_second=(
                    self._motor_state.angular_velocity_radians_per_second
                ),
            )
            self._motor_state = next_motor_state
            self._simulation_time_seconds = next_simulation_time
            self._revision += 1

    def preview_state(self) -> SimulationMotorPreviewState:
        """Return one side-effect-free state, time, and revision snapshot."""
        with self._preview_lock:
            return SimulationMotorPreviewState(
                angular_position_radians=self._motor_state.angular_position_radians,
                angular_velocity_radians_per_second=(
                    self._motor_state.angular_velocity_radians_per_second
                ),
                simulation_time_seconds=self._simulation_time_seconds,
                revision=self._revision,
            )

    async def _on_start(self) -> None:
        with self._preview_lock:
            self._motor_state = MotorState(
                angular_position_radians=0.0,
                angular_velocity_radians_per_second=0.0,
            )
            self._simulation_time_seconds = 0.0
            self._revision = 0

    async def _on_shutdown(self) -> None:
        with self._preview_lock:
            self._motor_state = MotorState(
                angular_position_radians=self._motor_state.angular_position_radians,
                angular_velocity_radians_per_second=0.0,
            )
            self._revision += 1

    async def _apply_command(self, command: MotorCommand) -> None:
        with self._preview_lock:
            self._motor_state = MotorState(
                angular_position_radians=self._motor_state.angular_position_radians,
                angular_velocity_radians_per_second=(
                    float(command.angular_velocity_radians_per_second)
                ),
            )
            self._revision += 1

    async def _read_state(self) -> MotorState:
        with self._preview_lock:
            return self._motor_state
