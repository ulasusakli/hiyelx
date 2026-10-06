"""Core resource contracts.

The lifecycle transition table is intentionally small and deterministic::

    CREATED  -> STARTING
    STARTING -> RUNNING | FAILED
    RUNNING  -> STOPPING
    STOPPING -> STOPPED | FAILED
    STOPPED  -> (terminal)
    FAILED   -> (terminal)

``start()`` owns the CREATED -> STARTING -> RUNNING path and ``shutdown()``
owns the RUNNING -> STOPPING -> STOPPED path. A hook exception moves the
resource from the corresponding transitional state to FAILED. Every other
transition is rejected without changing state.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType
from typing import Final, final

from hiyelx.resources.reliability import (
    DEFAULT_OPERATION_DEADLINES,
    BackendUnavailableError,
    OperationDeadlineExceeded,
    OperationDeadlinePolicy,
    await_with_deadline,
)


@dataclass(frozen=True, slots=True)
class ResourceIdentity:
    """Immutable, vendor-neutral identity for one resource."""

    value: str

    def __post_init__(self) -> None:
        if not self.value or self.value.isspace():
            msg = "resource identity must not be empty"
            raise ValueError(msg)

    def __str__(self) -> str:
        return self.value


class LifecycleState(Enum):
    """A resource's lifecycle state."""

    CREATED = "created"
    STARTING = "starting"
    RUNNING = "running"
    STOPPING = "stopping"
    STOPPED = "stopped"
    FAILED = "failed"


class HealthStatus(Enum):
    """Vendor-neutral health classification."""

    UNKNOWN = "unknown"
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"


@dataclass(frozen=True, slots=True)
class ResourceHealth:
    """A point-in-time, vendor-neutral health snapshot."""

    status: HealthStatus
    detail: str | None = None


LIFECYCLE_TRANSITIONS: Final[Mapping[LifecycleState, frozenset[LifecycleState]]] = (
    MappingProxyType(
        {
            LifecycleState.CREATED: frozenset({LifecycleState.STARTING}),
            LifecycleState.STARTING: frozenset(
                {LifecycleState.RUNNING, LifecycleState.FAILED}
            ),
            LifecycleState.RUNNING: frozenset({LifecycleState.STOPPING}),
            LifecycleState.STOPPING: frozenset(
                {LifecycleState.STOPPED, LifecycleState.FAILED}
            ),
            LifecycleState.STOPPED: frozenset(),
            LifecycleState.FAILED: frozenset(),
        }
    )
)
"""Allowed lifecycle state transitions. Terminal states map to empty sets."""


class ResourceLifecycleError(Exception):
    """Base class for typed resource lifecycle failures."""

    def __init__(self, identity: ResourceIdentity, message: str) -> None:
        self.identity = identity
        super().__init__(message)


class InvalidLifecycleTransition(ResourceLifecycleError):
    """Raised when an operation would require a disallowed transition."""

    def __init__(
        self,
        identity: ResourceIdentity,
        current_state: LifecycleState,
        target_state: LifecycleState,
    ) -> None:
        self.current_state = current_state
        self.target_state = target_state
        super().__init__(
            identity,
            f"resource {identity!s} cannot transition from "
            f"{current_state.value} to {target_state.value}",
        )


class ResourceStartupError(ResourceLifecycleError):
    """Raised when a resource's startup hook fails."""

    def __init__(self, identity: ResourceIdentity) -> None:
        super().__init__(identity, f"resource {identity!s} failed to start")


class ResourceShutdownError(ResourceLifecycleError):
    """Raised when a resource's shutdown hook fails."""

    def __init__(self, identity: ResourceIdentity) -> None:
        super().__init__(identity, f"resource {identity!s} failed to shut down")


class Resource:
    """Base resource with guarded lifecycle operations and async hooks.

    Subclasses customize behavior by overriding ``_on_start`` and
    ``_on_shutdown``. They may publish health snapshots with ``_set_health``;
    health is deliberately independent from lifecycle state.
    """

    def __init__(
        self,
        identity: ResourceIdentity,
        *,
        deadline_policy: OperationDeadlinePolicy = DEFAULT_OPERATION_DEADLINES,
    ) -> None:
        self._identity = identity
        self._state = LifecycleState.CREATED
        self._health = ResourceHealth(HealthStatus.UNKNOWN)
        self._deadline_policy = deadline_policy

    @property
    def identity(self) -> ResourceIdentity:
        """Return the resource's stable identity."""
        return self._identity

    @property
    def state(self) -> LifecycleState:
        """Return the current lifecycle state."""
        return self._state

    @property
    def health(self) -> ResourceHealth:
        """Return the latest immutable health snapshot."""
        return self._health

    @property
    def deadline_policy(self) -> OperationDeadlinePolicy:
        """Return the immutable deadline policy owned by this resource."""
        return self._deadline_policy

    @final
    async def start(self) -> None:
        """Start the resource or raise a typed lifecycle error."""
        self._transition_to(LifecycleState.STARTING)
        try:
            await await_with_deadline(
                self._on_start(),
                identity=self.identity,
                operation_name="startup",
                timeout_seconds=self.deadline_policy.startup_seconds,
                lifecycle_state=self.state,
            )
        except Exception as error:
            self._record_reliability_failure(error, "startup")
            self._transition_to(LifecycleState.FAILED)
            raise ResourceStartupError(self.identity) from error
        self._transition_to(LifecycleState.RUNNING)
        if self.health.status is HealthStatus.UNKNOWN:
            self._set_health(ResourceHealth(HealthStatus.HEALTHY))

    @final
    async def shutdown(self) -> None:
        """Shut down the resource or raise a typed lifecycle error."""
        self._transition_to(LifecycleState.STOPPING)
        try:
            await await_with_deadline(
                self._on_shutdown(),
                identity=self.identity,
                operation_name="shutdown",
                timeout_seconds=self.deadline_policy.shutdown_seconds,
                lifecycle_state=self.state,
            )
        except Exception as error:
            self._record_reliability_failure(error, "shutdown")
            self._transition_to(LifecycleState.FAILED)
            raise ResourceShutdownError(self.identity) from error
        self._transition_to(LifecycleState.STOPPED)

    async def _on_start(self) -> None:
        """Perform resource-specific asynchronous startup."""

    async def _on_shutdown(self) -> None:
        """Perform resource-specific asynchronous shutdown."""

    @final
    def _set_health(self, health: ResourceHealth) -> None:
        """Publish an immutable health snapshot for inspection."""
        self._health = health

    def _transition_to(self, target_state: LifecycleState) -> None:
        if target_state not in LIFECYCLE_TRANSITIONS[self.state]:
            raise InvalidLifecycleTransition(self.identity, self.state, target_state)
        self._state = target_state

    def _record_reliability_failure(self, error: Exception, operation: str) -> None:
        if isinstance(error, OperationDeadlineExceeded):
            detail = f"deadline exceeded during {operation}"
        elif isinstance(error, BackendUnavailableError):
            detail = f"backend unavailable during {operation}"
        else:
            return
        self._set_health(ResourceHealth(HealthStatus.UNHEALTHY, detail))
