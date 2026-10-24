"""Read-only local Runtime Operations snapshots and lifecycle façade."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from hiyelx.config import RuntimeConfig
from hiyelx.models import ModelRegistry
from hiyelx.resources import (
    HealthStatus,
    LifecycleState,
    ResourceIdentity,
    ResourceOperation,
)
from hiyelx.runtime.errors import SafeStopReport
from hiyelx.runtime.events import LocalEventRecorder, RuntimeEvent
from hiyelx.runtime.manager import RuntimeManager
from hiyelx.runtime.state import RuntimeManagerState

if TYPE_CHECKING:
    from hiyelx.simulation.preview import SimulationPreviewSnapshot


@dataclass(frozen=True, slots=True)
class RuntimeResourceSnapshot:
    """Immutable user-facing state for one runtime-owned resource."""

    identity: ResourceIdentity
    lifecycle_state: LifecycleState
    health_status: HealthStatus
    health_summary: str | None


@dataclass(frozen=True, slots=True)
class RuntimeOperationsSnapshot:
    """Complete immutable point-in-operation view of one local runtime."""

    manager_state: RuntimeManagerState
    resources: tuple[RuntimeResourceSnapshot, ...]
    startup_plan: tuple[ResourceIdentity, ...]
    successful_start_order: tuple[ResourceIdentity, ...]
    active_resource_order: tuple[ResourceIdentity, ...]
    event_high_water_mark: int | None
    events: tuple[RuntimeEvent, ...]


class RuntimeOperations:
    """Instance-local owner and explicit lifecycle façade for one runtime."""

    def __init__(self, config: RuntimeConfig, registry: ModelRegistry) -> None:
        self._event_recorder = LocalEventRecorder()
        self._manager = RuntimeManager(config, registry, event_sink=self._event_recorder)

    def snapshot(self) -> RuntimeOperationsSnapshot:
        """Return a deterministic view without invoking lifecycle work or I/O."""
        resources = tuple(
            self._resource_snapshot(identity) for identity in self._manager.startup_plan
        )
        events = self._event_recorder.events
        return RuntimeOperationsSnapshot(
            manager_state=self._manager.state,
            resources=resources,
            startup_plan=self._manager.startup_plan,
            successful_start_order=self._manager.successful_start_order,
            active_resource_order=self._manager.active_resource_order,
            event_high_water_mark=self._event_recorder.high_water_mark,
            events=events,
        )

    def simulation_preview_snapshot(self) -> SimulationPreviewSnapshot:
        """Return the typed simulation preview without exposing the manager."""
        from hiyelx.simulation.preview import SimulationPreviewProvider

        return SimulationPreviewProvider(self._manager).snapshot()

    async def start(self) -> None:
        """Explicitly delegate startup to the owned Runtime Manager."""
        await self._manager.start()

    async def safe_stop(
        self,
        *,
        primary_failure: Exception | None = None,
    ) -> SafeStopReport:
        """Explicitly delegate best-effort safe-stop to the owned manager."""
        return await self._manager.safe_stop(primary_failure=primary_failure)

    async def shutdown(self) -> None:
        """Explicitly delegate shutdown to the owned Runtime Manager."""
        await self._manager.shutdown()

    def _resource_snapshot(self, identity: ResourceIdentity) -> RuntimeResourceSnapshot:
        resource = self._manager.get_resource(identity)
        return RuntimeResourceSnapshot(
            identity=resource.identity,
            lifecycle_state=resource.state,
            health_status=resource.health.status,
            health_summary=sanitize_health_summary(resource.health.detail),
        )


_SANITIZED_HEALTH_SUMMARIES = frozenset(
    f"{prefix} during {operation.value}"
    for prefix in (
        "deadline exceeded",
        "backend unavailable",
        "safe-stop failed",
        "lifecycle cleanup failed",
    )
    for operation in ResourceOperation
)


def sanitize_health_summary(detail: str | None) -> str | None:
    """Return only fixed HIYELX-owned health wording."""
    if detail in _SANITIZED_HEALTH_SUMMARIES:
        return detail
    return None
