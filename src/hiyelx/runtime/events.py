"""Immutable instance-local Runtime Manager event contracts."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, StrEnum
from typing import Protocol

from hiyelx.resources import HealthStatus, LifecycleState, ResourceIdentity


class RuntimeEventOutcome(Enum):
    """Stable outcome classification for one runtime operation record."""

    REQUESTED = "requested"
    ATTEMPTED = "attempted"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    COMPLETED = "completed"


class RuntimeEventOperation(StrEnum):
    """Stable operation names emitted by the local runtime."""

    RUNTIME_START = "runtime_start"
    RESOURCE_START = "resource_start"
    STARTUP_ROLLBACK = "startup_rollback"
    RUNTIME_RUNNING = "runtime_running"
    RUNTIME_SHUTDOWN = "runtime_shutdown"
    RESOURCE_SHUTDOWN = "resource_shutdown"
    RUNTIME_STOPPED = "runtime_stopped"
    RUNTIME_FAILED = "runtime_failed"
    SAFE_STOP = "safe_stop"
    HEALTH_DEGRADATION = "health_degradation"
    SAFE_STOP_CLEANUP = "safe_stop_cleanup"


@dataclass(frozen=True, slots=True)
class RuntimeEvent:
    """One immutable, sanitized runtime event with deterministic ordering."""

    sequence: int
    operation: RuntimeEventOperation
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
    def events(self) -> tuple[RuntimeEvent, ...]:
        """Return an immutable ordered snapshot."""
        return tuple(self._events)

    @property
    def high_water_mark(self) -> int | None:
        """Return the latest retained sequence, or ``None`` when empty."""
        if not self._events:
            return None
        return self._events[-1].sequence
