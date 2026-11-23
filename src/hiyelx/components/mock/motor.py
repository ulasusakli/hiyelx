"""Canonical Mock Motor for hardware-free simulation."""

from __future__ import annotations

from threading import RLock
from typing import TYPE_CHECKING

from hiyelx.components.motor import Motor, MotorCommand, MotorState

if TYPE_CHECKING:
    from hiyelx.config.v2.models import ComponentDefinition
from hiyelx.resources import (
    DEFAULT_OPERATION_DEADLINES,
    OperationDeadlinePolicy,
    ResourceIdentity,
)


class MockMotor(Motor):
    """Deterministic simulated motor adhering to ACTUATOR category."""

    def __init__(
        self,
        identity: ResourceIdentity,
        *,
        max_rpm: float = 300.0,
        deadline_policy: OperationDeadlinePolicy = DEFAULT_OPERATION_DEADLINES,
    ) -> None:
        super().__init__(identity, deadline_policy=deadline_policy)
        self._max_rpm = max_rpm
        self._lock = RLock()
        self._position_radians = 0.0
        self._velocity_radians_per_second = 0.0

    @property
    def max_rpm(self) -> float:
        """Return the configured maximum RPM."""
        return self._max_rpm

    async def _apply_command(self, command: MotorCommand) -> None:
        with self._lock:
            self._velocity_radians_per_second = command.angular_velocity_radians_per_second

    async def _read_state(self) -> MotorState:
        with self._lock:
            return MotorState(
                angular_position_radians=self._position_radians,
                angular_velocity_radians_per_second=self._velocity_radians_per_second,
            )

    def step(self, time_step_seconds: float) -> None:
        """Advance simulated motor position deterministically."""
        with self._lock:
            self._position_radians += self._velocity_radians_per_second * time_step_seconds


def create_mock_motor(definition: ComponentDefinition) -> MockMotor:
    """Factory creating a MockMotor from a ComponentDefinition."""
    max_rpm = float(definition.settings.get("max_rpm", 300.0))  # type: ignore
    return MockMotor(definition.id, max_rpm=max_rpm)
