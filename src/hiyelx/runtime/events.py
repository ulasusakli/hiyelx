"""Immutable instance-local Runtime Manager event contracts."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from enum import Enum
from typing import Protocol

from hiyelx.resources import HealthStatus, LifecycleState, ResourceIdentity


class RuntimeEventOutcome(Enum):
    """Stable outcome classification for one runtime operation record."""

    REQUESTED = "requested"
    ATTEMPTED = "attempted"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    COMPLETED = "completed"


@dataclass(frozen=True, slots=True)
class RuntimeEvent:
    """One immutable, sanitized runtime event with deterministic ordering."""

    sequence: int
    operation: str
    outcome: RuntimeEventOutcome
    summary: str
    identity: ResourceIdentity | None = None
    lifecycle_state: LifecycleState | None = None
    health_status: HealthStatus | None = None


class RuntimeEventSink(Protocol):
    """Instance-local destination for already-sanitized runtime events."""

    def record(self, event: RuntimeEvent) -> None:
        """Record one event in call order."""


class LocalEventRecorder:
    """In-memory recorder whose snapshot cannot mutate retained events."""

    def __init__(self) -> None:
        self._events: list[RuntimeEvent] = []

    def record(self, event: RuntimeEvent) -> None:
        self._events.append(event)

    @property
    def events(self) -> Sequence[RuntimeEvent]:
        """Return an immutable ordered snapshot."""
        return tuple(self._events)
