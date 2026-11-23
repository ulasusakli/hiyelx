"""Canonical Mock Encoder for hardware-free simulation."""

from __future__ import annotations

from math import pi
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


class MockEncoder(Component):
    """Deterministic simulated rotary encoder adhering to FEEDBACK category."""

    def __init__(
        self,
        identity: ResourceIdentity,
        *,
        resolution_cpr: int = 4096,
        deadline_policy: OperationDeadlinePolicy = DEFAULT_OPERATION_DEADLINES,
    ) -> None:
        super().__init__(
            identity,
            category=ComponentCategory.FEEDBACK,
            capabilities=(
                ComponentCapability.HAS_ENCODER_TICKS,
                ComponentCapability.HAS_ANGULAR_POSITION,
                ComponentCapability.HAS_ANGULAR_VELOCITY,
            ),
            deadline_policy=deadline_policy,
        )
        self._resolution_cpr = resolution_cpr
        self._lock = RLock()
        self._ticks = 0
        self._velocity = 0.0

    @property
    def resolution_cpr(self) -> int:
        """Return counts per revolution."""
        return self._resolution_cpr

    @property
    def ticks(self) -> int:
        """Return the current raw tick count."""
        with self._lock:
            return self._ticks

    @property
    def position_radians(self) -> float:
        """Return current angular position in radians."""
        with self._lock:
            return (self._ticks / self._resolution_cpr) * (2.0 * pi)

    def set_ticks(self, ticks: int) -> None:
        """Set raw ticks explicitly."""
        with self._lock:
            self._ticks = ticks

    def update_ticks(self, delta_ticks: int) -> None:
        """Add delta ticks to current count."""
        with self._lock:
            self._ticks += delta_ticks


def create_mock_encoder(definition: ComponentDefinition) -> MockEncoder:
    """Factory creating a MockEncoder from a ComponentDefinition."""
    cpr = int(definition.settings.get("resolution", 4096))  # type: ignore
    return MockEncoder(definition.id, resolution_cpr=cpr)
