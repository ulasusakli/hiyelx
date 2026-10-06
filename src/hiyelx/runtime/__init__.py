"""Deterministic local resource ownership and lifecycle management."""

from hiyelx.runtime.errors import (
    DependencyCycleError,
    DuplicateDependencyError,
    InvalidRuntimeManagerStateError,
    MissingDependencyError,
    ResourceIdentityMismatchError,
    RollbackFailure,
    RuntimeConstructionError,
    RuntimeManagerError,
    RuntimeSafeStopError,
    RuntimeShutdownError,
    RuntimeStartupError,
    RuntimeTopologyError,
    SafeStopOutcome,
    SafeStopReport,
    SelfDependencyError,
    ShutdownFailure,
    UnknownOwnedResourceError,
)
from hiyelx.runtime.events import (
    LocalEventRecorder,
    RuntimeEvent,
    RuntimeEventOutcome,
    RuntimeEventSink,
)
from hiyelx.runtime.manager import RuntimeManager
from hiyelx.runtime.state import RuntimeManagerOperation, RuntimeManagerState

__all__ = [
    "DependencyCycleError",
    "DuplicateDependencyError",
    "InvalidRuntimeManagerStateError",
    "MissingDependencyError",
    "ResourceIdentityMismatchError",
    "RollbackFailure",
    "RuntimeConstructionError",
    "RuntimeManager",
    "RuntimeManagerError",
    "RuntimeManagerOperation",
    "RuntimeManagerState",
    "RuntimeShutdownError",
    "RuntimeSafeStopError",
    "RuntimeStartupError",
    "RuntimeTopologyError",
    "SelfDependencyError",
    "ShutdownFailure",
    "SafeStopOutcome",
    "SafeStopReport",
    "LocalEventRecorder",
    "RuntimeEvent",
    "RuntimeEventOutcome",
    "RuntimeEventSink",
    "UnknownOwnedResourceError",
]
