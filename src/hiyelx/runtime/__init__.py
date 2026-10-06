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
    RuntimeShutdownError,
    RuntimeStartupError,
    RuntimeTopologyError,
    SelfDependencyError,
    ShutdownFailure,
    UnknownOwnedResourceError,
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
    "RuntimeStartupError",
    "RuntimeTopologyError",
    "SelfDependencyError",
    "ShutdownFailure",
    "UnknownOwnedResourceError",
]
