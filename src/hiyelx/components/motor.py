"""Vendor-neutral motor contract.

Angular position is expressed in radians and angular velocity in radians per
second. Motor commands are accepted only while the resource lifecycle state is
``RUNNING``. The latest motor state remains inspectable in every lifecycle
state so callers can verify initialization and shutdown outcomes.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from math import isfinite
from typing import final

from hiyelx.resources import (
    LifecycleState,
    Resource,
    ResourceIdentity,
)
from hiyelx.resources.reliability import await_with_deadline


class MotorError(Exception):
    """Base class for typed motor contract errors."""


class InvalidMotorCommandError(MotorError):
    """Raised when a motor command contains an invalid value."""

    def __init__(self, angular_velocity_radians_per_second: float) -> None:
        self.angular_velocity_radians_per_second = angular_velocity_radians_per_second
        super().__init__("motor angular velocity must be finite")


class InvalidMotorStateError(MotorError):
    """Raised when a motor state contains an invalid value."""

    def __init__(self, field: str, value: float) -> None:
        self.field = field
        self.value = value
        super().__init__(f"motor state {field} must be finite")


class MotorUnavailableError(MotorError):
    """Raised when a motor command is issued outside RUNNING."""

    def __init__(
        self,
        identity: ResourceIdentity,
        lifecycle_state: LifecycleState,
    ) -> None:
        self.identity = identity
        self.lifecycle_state = lifecycle_state
        super().__init__(
            f"motor {identity!s} cannot accept commands while {lifecycle_state.value}"
        )


@dataclass(frozen=True, slots=True)
class MotorCommand:
    """A velocity command in radians per second.

    Negative values command rotation in the opposite direction. Non-finite
    values are invalid.
    """

    angular_velocity_radians_per_second: float

    def __post_init__(self) -> None:
        if not isfinite(self.angular_velocity_radians_per_second):
            raise InvalidMotorCommandError(self.angular_velocity_radians_per_second)

    @classmethod
    def zero_velocity(cls) -> MotorCommand:
        """Return a command for zero angular velocity."""
        return cls(angular_velocity_radians_per_second=0.0)


@dataclass(frozen=True, slots=True)
class MotorState:
    """A motor snapshot in radians and radians per second."""

    angular_position_radians: float
    angular_velocity_radians_per_second: float

    def __post_init__(self) -> None:
        values = (
            ("angular_position_radians", self.angular_position_radians),
            (
                "angular_velocity_radians_per_second",
                self.angular_velocity_radians_per_second,
            ),
        )
        for field, value in values:
            if not isfinite(value):
                raise InvalidMotorStateError(field, value)


class Motor(Resource, ABC):
    """Application-level motor abstraction with lifecycle-guarded commands."""

    @final
    async def apply_command(self, command: MotorCommand) -> None:
        """Apply a velocity command while the motor is RUNNING."""
        self._require_running()
        try:
            await await_with_deadline(
                self._apply_command(command),
                identity=self.identity,
                operation_name="motor_command",
                timeout_seconds=self.deadline_policy.motor_command_seconds,
                lifecycle_state=self.state,
            )
        except Exception as error:
            self._record_reliability_failure(error, "motor command")
            raise

    @final
    async def read_state(self) -> MotorState:
        """Return the latest motor state snapshot in SI angular units."""
        try:
            return await await_with_deadline(
                self._read_state(),
                identity=self.identity,
                operation_name="motor_state_read",
                timeout_seconds=self.deadline_policy.motor_state_read_seconds,
                lifecycle_state=self.state,
            )
        except Exception as error:
            self._record_reliability_failure(error, "motor state read")
            raise

    @final
    async def stop(self) -> None:
        """Command zero angular velocity while the motor is RUNNING."""
        await self.apply_command(MotorCommand.zero_velocity())

    @abstractmethod
    async def _apply_command(self, command: MotorCommand) -> None:
        """Apply a validated command in a concrete backend."""

    @abstractmethod
    async def _read_state(self) -> MotorState:
        """Read the latest state from a concrete backend."""

    @final
    def _require_running(self) -> None:
        if self.state is not LifecycleState.RUNNING:
            raise MotorUnavailableError(self.identity, self.state)
