"""Canonical Mock Camera for hardware-free simulation."""

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


class MockCamera(Component):
    """Deterministic simulated camera adhering to VISION category."""

    def __init__(
        self,
        identity: ResourceIdentity,
        *,
        width: int = 640,
        height: int = 480,
        fps: int = 30,
        deadline_policy: OperationDeadlinePolicy = DEFAULT_OPERATION_DEADLINES,
    ) -> None:
        super().__init__(
            identity,
            category=ComponentCategory.VISION,
            capabilities=(
                ComponentCapability.CAN_STREAM_FRAMES,
                ComponentCapability.HAS_RGB_FRAME,
            ),
            deadline_policy=deadline_policy,
        )
        self._width = width
        self._height = height
        self._fps = fps
        self._lock = RLock()
        self._frame_count = 0

    @property
    def resolution(self) -> tuple[int, int]:
        """Return frame width and height."""
        return self._width, self._height

    @property
    def fps(self) -> int:
        """Return configured frames per second."""
        return self._fps

    @property
    def frame_count(self) -> int:
        """Return the number of captured frames."""
        with self._lock:
            return self._frame_count

    def capture_frame(self) -> bytes:
        """Produce synthetic RGB frame data."""
        with self._lock:
            self._frame_count += 1
            # Generate deterministic synthetic frame bytes (1 byte per channel pixel)
            fill_byte = bytes([(self._frame_count % 256)])
            return fill_byte * (self._width * self._height * 3)


def create_mock_camera(definition: ComponentDefinition) -> MockCamera:
    """Factory creating a MockCamera from a ComponentDefinition."""
    width = int(definition.settings.get("width", 640))  # type: ignore
    height = int(definition.settings.get("height", 480))  # type: ignore
    fps = int(definition.settings.get("fps", 30))  # type: ignore
    return MockCamera(definition.id, width=width, height=height, fps=fps)
