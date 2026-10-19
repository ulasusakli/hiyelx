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


_ALLOWED_EVENT_SUMMARIES = frozenset(
    {
        (
            RuntimeEventOperation.RUNTIME_START,
            RuntimeEventOutcome.REQUESTED,
            "runtime start requested",
        ),
        (
            RuntimeEventOperation.RESOURCE_START,
            RuntimeEventOutcome.ATTEMPTED,
            "resource start attempted",
        ),
        (
            RuntimeEventOperation.RESOURCE_START,
            RuntimeEventOutcome.FAILED,
            "resource start failed",
        ),
        (
            RuntimeEventOperation.RUNTIME_FAILED,
            RuntimeEventOutcome.FAILED,
            "runtime failed during startup",
        ),
        (
            RuntimeEventOperation.RESOURCE_START,
            RuntimeEventOutcome.SUCCEEDED,
            "resource start succeeded",
        ),
        (
            RuntimeEventOperation.RUNTIME_RUNNING,
            RuntimeEventOutcome.SUCCEEDED,
            "runtime running",
        ),
        (
            RuntimeEventOperation.RUNTIME_SHUTDOWN,
            RuntimeEventOutcome.REQUESTED,
            "runtime shutdown requested",
        ),
        (
            RuntimeEventOperation.RESOURCE_SHUTDOWN,
            RuntimeEventOutcome.ATTEMPTED,
            "resource shutdown attempted",
        ),
        (
            RuntimeEventOperation.RESOURCE_SHUTDOWN,
            RuntimeEventOutcome.FAILED,
            "resource shutdown failed",
        ),
        (
            RuntimeEventOperation.RESOURCE_SHUTDOWN,
            RuntimeEventOutcome.SUCCEEDED,
            "resource shutdown succeeded",
        ),
        (
            RuntimeEventOperation.RUNTIME_FAILED,
            RuntimeEventOutcome.FAILED,
            "runtime failed during shutdown",
        ),
        (
            RuntimeEventOperation.RUNTIME_STOPPED,
            RuntimeEventOutcome.SUCCEEDED,
            "runtime stopped",
        ),
        (
            RuntimeEventOperation.SAFE_STOP,
            RuntimeEventOutcome.REQUESTED,
            "safe-stop requested",
        ),
        (
            RuntimeEventOperation.SAFE_STOP,
            RuntimeEventOutcome.ATTEMPTED,
            "motor safe-stop attempted",
        ),
        (
            RuntimeEventOperation.HEALTH_DEGRADATION,
            RuntimeEventOutcome.FAILED,
            "resource health degraded after safe-stop failure",
        ),
        (
            RuntimeEventOperation.SAFE_STOP,
            RuntimeEventOutcome.FAILED,
            "motor safe-stop failed",
        ),
        (
            RuntimeEventOperation.SAFE_STOP,
            RuntimeEventOutcome.SUCCEEDED,
            "motor safe-stop succeeded",
        ),
        (
            RuntimeEventOperation.SAFE_STOP_CLEANUP,
            RuntimeEventOutcome.COMPLETED,
            "safe-stop cleanup completed",
        ),
        (
            RuntimeEventOperation.STARTUP_ROLLBACK,
            RuntimeEventOutcome.ATTEMPTED,
            "startup rollback attempted",
        ),
        (
            RuntimeEventOperation.RESOURCE_SHUTDOWN,
            RuntimeEventOutcome.ATTEMPTED,
            "resource shutdown attempted during startup rollback",
        ),
        (
            RuntimeEventOperation.RESOURCE_SHUTDOWN,
            RuntimeEventOutcome.FAILED,
            "resource shutdown failed during startup rollback",
        ),
        (
            RuntimeEventOperation.RESOURCE_SHUTDOWN,
            RuntimeEventOutcome.SUCCEEDED,
            "resource shutdown succeeded during startup rollback",
        ),
        (
            RuntimeEventOperation.STARTUP_ROLLBACK,
            RuntimeEventOutcome.COMPLETED,
            "startup rollback completed",
        ),
    }
)

_RESOURCE_EVENT_KEYS = frozenset(
    {
        (RuntimeEventOperation.RESOURCE_START, RuntimeEventOutcome.ATTEMPTED),
        (RuntimeEventOperation.RESOURCE_START, RuntimeEventOutcome.FAILED),
        (RuntimeEventOperation.RESOURCE_START, RuntimeEventOutcome.SUCCEEDED),
        (RuntimeEventOperation.RESOURCE_SHUTDOWN, RuntimeEventOutcome.ATTEMPTED),
        (RuntimeEventOperation.RESOURCE_SHUTDOWN, RuntimeEventOutcome.FAILED),
        (RuntimeEventOperation.RESOURCE_SHUTDOWN, RuntimeEventOutcome.SUCCEEDED),
        (RuntimeEventOperation.SAFE_STOP, RuntimeEventOutcome.ATTEMPTED),
        (RuntimeEventOperation.SAFE_STOP, RuntimeEventOutcome.FAILED),
        (RuntimeEventOperation.SAFE_STOP, RuntimeEventOutcome.SUCCEEDED),
        (RuntimeEventOperation.HEALTH_DEGRADATION, RuntimeEventOutcome.FAILED),
    }
)


def validate_persistable_runtime_event(event: RuntimeEvent) -> None:
    """Reject fields outside the fixed sanitized RTO-1 event contract."""
    if (
        type(event.sequence) is not int
        or event.sequence < 0
        or type(event.operation) is not RuntimeEventOperation
        or type(event.outcome) is not RuntimeEventOutcome
        or (event.operation, event.outcome, event.summary)
        not in _ALLOWED_EVENT_SUMMARIES
    ):
        raise ValueError
    resource_event = (event.operation, event.outcome) in _RESOURCE_EVENT_KEYS
    if resource_event:
        if (
            not isinstance(event.identity, ResourceIdentity)
            or not _is_safe_resource_identity(event.identity)
            or not isinstance(event.lifecycle_state, LifecycleState)
            or not isinstance(event.health_status, HealthStatus)
        ):
            raise ValueError
    elif (
        event.identity is not None
        or event.lifecycle_state is not None
        or event.health_status is not None
    ):
        raise ValueError


def persisted_event_severity(event: RuntimeEvent) -> str:
    """Return the fixed persisted severity for one validated event."""
    validate_persistable_runtime_event(event)
    if event.operation is RuntimeEventOperation.HEALTH_DEGRADATION:
        return "warning"
    if event.outcome is RuntimeEventOutcome.FAILED:
        return "error"
    return "info"


def _is_safe_resource_identity(identity: ResourceIdentity) -> bool:
    value = identity.value
    return (
        1 <= len(value) <= 64
        and value[0].isascii()
        and (value[0].islower() or value[0].isdigit())
        and all(
            character.isascii()
            and (
                character.islower()
                or character.isdigit()
                or character in "_-"
            )
            for character in value
        )
    )
