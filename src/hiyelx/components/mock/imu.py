"""Canonical Mock IMU for hardware-free simulation."""

from __future__ import annotations

from threading import RLock
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from hiyelx.config.v2.models import ComponentDefinition
from hiyelx.core.capabilities import ComponentCapability
from hiyelx.core.component import Component
from hiyelx.core.types import ComponentCategory
from hiyelx.resources import (
    DEFAULT_OPERATION_DEADLINES,
    OperationDeadlinePolicy,
    ResourceIdentity,
)


class MockIMU(Component):
    """Deterministic simulated 9-DOF IMU adhering to SPATIAL category."""

    def __init__(
        self,
        identity: ResourceIdentity,
        *,
        sample_rate_hz: float = 100.0,
        deadline_policy: OperationDeadlinePolicy = DEFAULT_OPERATION_DEADLINES,
    ) -> None:
        super().__init__(
            identity,
            category=ComponentCategory.SPATIAL,
            capabilities=(
                ComponentCapability.HAS_ORIENTATION_QUATERNION,
                ComponentCapability.HAS_ANGULAR_VELOCITY_3D,
                ComponentCapability.HAS_LINEAR_ACCELERATION_3D,
            ),
            deadline_policy=deadline_policy,
        )
        self._sample_rate_hz = sample_rate_hz
        self._lock = RLock()
        self._quaternion = (0.0, 0.0, 0.0, 1.0)
        self._angular_velocity = (0.0, 0.0, 0.0)
        self._linear_acceleration = (0.0, 0.0, 9.81)

    @property
    def sample_rate_hz(self) -> float:
        """Return configured sensor sample rate."""
        return self._sample_rate_hz

    @property
    def orientation(self) -> tuple[float, float, float, float]:
        """Return current orientation quaternion (x, y, z, w)."""
        with self._lock:
            return self._quaternion

    @property
    def angular_velocity(self) -> tuple[float, float, float]:
        """Return angular velocity (roll_rate, pitch_rate, yaw_rate) in rad/s."""
        with self._lock:
            return self._angular_velocity

    @property
    def linear_acceleration(self) -> tuple[float, float, float]:
        """Return linear acceleration (ax, ay, az) in m/s^2."""
        with self._lock:
            return self._linear_acceleration

    def set_orientation(self, x: float, y: float, z: float, w: float) -> None:
        """Set orientation quaternion explicitly."""
        with self._lock:
            self._quaternion = (x, y, z, w)

    def set_motion(
        self,
        angular_velocity: tuple[float, float, float],
        linear_acceleration: tuple[float, float, float],
    ) -> None:
        """Set angular velocity and linear acceleration."""
        with self._lock:
            self._angular_velocity = angular_velocity
            self._linear_acceleration = linear_acceleration


def create_mock_imu(definition: ComponentDefinition) -> MockIMU:
    """Factory creating a MockIMU from a ComponentDefinition."""
    rate = float(definition.settings.get("sample_rate_hz", 100.0))  # type: ignore
    return MockIMU(definition.id, sample_rate_hz=rate)
