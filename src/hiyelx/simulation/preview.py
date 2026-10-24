"""Renderer-neutral, read-only snapshots for deterministic simulation."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Literal, cast

from hiyelx.resources import HealthStatus, LifecycleState, ResourceIdentity
from hiyelx.runtime.manager import RuntimeManager
from hiyelx.runtime.operations import sanitize_health_summary
from hiyelx.runtime.state import RuntimeManagerState
from hiyelx.simulation.motor import SimulatedMotor, SimulationMotorPreviewState

SIMULATION_PREVIEW_SCHEMA_VERSION = "1"

_TRANSITIONAL_RUNTIME_STATES = frozenset(
    {RuntimeManagerState.STARTING, RuntimeManagerState.STOPPING}
)


class SimulationPreviewError(Exception):
    """Base class for typed in-process simulation preview failures."""


class InvalidSimulationPreviewSnapshotError(SimulationPreviewError, ValueError):
    """Raised when a preview value object violates the frozen schema."""

    def __init__(self, field: str) -> None:
        self.field = field
        super().__init__(f"simulation preview {field} is invalid")


class UnsupportedSimulationPreviewResourceError(SimulationPreviewError):
    """Raised when the runtime owns a resource outside Preview Alpha."""

    def __init__(self, identity: ResourceIdentity) -> None:
        self.identity = identity
        super().__init__("simulation preview resource is unsupported")


class SimulationPreviewUnavailableError(SimulationPreviewError):
    """Raised when a coherent read cannot be produced without retrying."""

    def __init__(self) -> None:
        super().__init__("simulation preview is temporarily unavailable")


@dataclass(frozen=True, slots=True)
class SimulationPreviewResourceSnapshot:
    """Immutable application projection for one simulated motor."""

    identity: ResourceIdentity
    kind: Literal["motor"]
    lifecycle_state: LifecycleState
    health_status: HealthStatus
    health_summary: str | None
    state: SimulationMotorPreviewState

    def __post_init__(self) -> None:
        if not isinstance(cast(object, self.identity), ResourceIdentity):
            raise InvalidSimulationPreviewSnapshotError("identity")
        if type(self.kind) is not str or self.kind != "motor":
            raise InvalidSimulationPreviewSnapshotError("kind")
        if not isinstance(cast(object, self.lifecycle_state), LifecycleState):
            raise InvalidSimulationPreviewSnapshotError("lifecycle_state")
        if not isinstance(cast(object, self.health_status), HealthStatus):
            raise InvalidSimulationPreviewSnapshotError("health_status")
        if self.health_summary is not None and (
            not isinstance(cast(object, self.health_summary), str)
            or sanitize_health_summary(self.health_summary) != self.health_summary
        ):
            raise InvalidSimulationPreviewSnapshotError("health_summary")
        if not isinstance(cast(object, self.state), SimulationMotorPreviewState):
            raise InvalidSimulationPreviewSnapshotError("state")


@dataclass(frozen=True, slots=True)
class SimulationPreviewSnapshot:
    """One versioned runtime-level deterministic preview projection."""

    schema_version: Literal["1"]
    runtime_state: RuntimeManagerState
    resources: tuple[SimulationPreviewResourceSnapshot, ...]

    def __post_init__(self) -> None:
        if (
            type(self.schema_version) is not str
            or self.schema_version != SIMULATION_PREVIEW_SCHEMA_VERSION
        ):
            raise InvalidSimulationPreviewSnapshotError("schema_version")
        if not isinstance(cast(object, self.runtime_state), RuntimeManagerState):
            raise InvalidSimulationPreviewSnapshotError("runtime_state")
        if type(self.resources) is not tuple or not all(
            isinstance(cast(object, resource), SimulationPreviewResourceSnapshot)
            for resource in self.resources
        ):
            raise InvalidSimulationPreviewSnapshotError("resources")
        identities = tuple(resource.identity for resource in self.resources)
        if len(set(identities)) != len(identities):
            raise InvalidSimulationPreviewSnapshotError("resources")


class SimulationPreviewProvider:
    """Project one existing Runtime Manager into the Preview Alpha schema."""

    def __init__(self, runtime: RuntimeManager) -> None:
        self._runtime = runtime

    def snapshot(self) -> SimulationPreviewSnapshot:
        """Return a coherent read or fail closed when mutation overlaps it."""
        runtime_state = self._runtime.state
        if runtime_state in _TRANSITIONAL_RUNTIME_STATES:
            raise SimulationPreviewUnavailableError

        resources: list[SimulationPreviewResourceSnapshot] = []
        for identity in self._runtime.startup_plan:
            resource = self._runtime.get_resource(identity)
            if not isinstance(resource, SimulatedMotor):
                raise UnsupportedSimulationPreviewResourceError(identity)

            state_before = resource.preview_state()
            lifecycle_state = resource.state
            health = resource.health
            state_after = resource.preview_state()
            if state_before != state_after:
                raise SimulationPreviewUnavailableError

            resources.append(
                SimulationPreviewResourceSnapshot(
                    identity=resource.identity,
                    kind="motor",
                    lifecycle_state=lifecycle_state,
                    health_status=health.status,
                    health_summary=sanitize_health_summary(health.detail),
                    state=state_after,
                )
            )

        if self._runtime.state is not runtime_state:
            raise SimulationPreviewUnavailableError
        return SimulationPreviewSnapshot(
            schema_version=SIMULATION_PREVIEW_SCHEMA_VERSION,
            runtime_state=runtime_state,
            resources=tuple(resources),
        )


def render_simulation_preview_json(snapshot: SimulationPreviewSnapshot) -> str:
    """Render one canonical compact JSON document with a trailing newline."""
    document = {
        "resources": [
            {
                "health_status": resource.health_status.value,
                "health_summary": resource.health_summary,
                "identity": resource.identity.value,
                "kind": resource.kind,
                "lifecycle_state": resource.lifecycle_state.value,
                "state": {
                    "angular_position_radians": (
                        resource.state.angular_position_radians
                    ),
                    "angular_velocity_radians_per_second": (
                        resource.state.angular_velocity_radians_per_second
                    ),
                    "revision": resource.state.revision,
                    "simulation_time_seconds": (
                        resource.state.simulation_time_seconds
                    ),
                },
            }
            for resource in snapshot.resources
        ],
        "runtime_state": snapshot.runtime_state.value,
        "schema_version": snapshot.schema_version,
    }
    return json.dumps(
        document,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ) + "\n"
