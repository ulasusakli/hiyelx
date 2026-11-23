"""Core component taxonomy and enumeration types."""

from __future__ import annotations

from enum import StrEnum


class ComponentCategory(StrEnum):
    """Broad functional categories for heterogeneous robotic components."""

    ACTUATOR = "actuator"
    VISION = "vision"
    SPATIAL = "spatial"
    FEEDBACK = "feedback"
    SERVICE = "service"

    def __str__(self) -> str:
        return self.value
