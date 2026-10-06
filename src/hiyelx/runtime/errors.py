"""Typed Runtime Manager topology, ownership, and lifecycle errors."""

from dataclasses import dataclass

from hiyelx.resources import ResourceIdentity
from hiyelx.runtime.state import RuntimeManagerOperation, RuntimeManagerState


class RuntimeManagerError(Exception):
    """Base class for Runtime Manager errors."""


class RuntimeTopologyError(RuntimeManagerError):
    """Base class for invalid dependency topology."""


class MissingDependencyError(RuntimeTopologyError):
    """Raised when a dependency is absent from the same runtime configuration."""

    def __init__(
        self,
        identity: ResourceIdentity,
        dependency: ResourceIdentity,
    ) -> None:
        self.identity = identity
        self.dependency = dependency
        super().__init__(f"resource {identity!s} depends on missing resource {dependency!s}")


class DuplicateDependencyError(RuntimeTopologyError):
    """Raised when one resource declares the same dependency more than once."""

    def __init__(
        self,
        identity: ResourceIdentity,
        dependency: ResourceIdentity,
    ) -> None:
        self.identity = identity
        self.dependency = dependency
        super().__init__(
            f"resource {identity!s} declares dependency {dependency!s} more than once"
        )


class SelfDependencyError(RuntimeTopologyError):
    """Raised when a resource declares itself as a dependency."""

    def __init__(self, identity: ResourceIdentity) -> None:
        self.identity = identity
        super().__init__(f"resource {identity!s} cannot depend on itself")


class DependencyCycleError(RuntimeTopologyError):
    """Raised when the dependency graph contains a cycle."""

    def __init__(self, identities: tuple[ResourceIdentity, ...]) -> None:
        self.identities = identities
        joined = ", ".join(str(identity) for identity in identities)
        super().__init__(f"dependency cycle contains: {joined}")


class RuntimeConstructionError(RuntimeManagerError):
    """Raised when a configured resource cannot be created for ownership."""

    def __init__(self, identity: ResourceIdentity, model_name: str) -> None:
        self.identity = identity
        self.model_name = model_name
        super().__init__(f"cannot construct resource {identity!s} from model {model_name!r}")


class ResourceIdentityMismatchError(RuntimeManagerError):
    """Raised when a factory returns a Resource with the wrong identity."""

    def __init__(
        self,
        expected: ResourceIdentity,
        actual: ResourceIdentity,
    ) -> None:
        self.expected = expected
        self.actual = actual
        super().__init__(f"factory returned resource {actual!s}; expected {expected!s}")


class UnknownOwnedResourceError(RuntimeManagerError):
    """Raised when lookup targets an identity not owned by the manager."""

    def __init__(self, identity: ResourceIdentity) -> None:
        self.identity = identity
        super().__init__(f"runtime does not own resource {identity!s}")


class InvalidRuntimeManagerStateError(RuntimeManagerError):
    """Raised when a lifecycle operation is invalid for the manager state."""

    def __init__(
        self,
        current_state: RuntimeManagerState,
        operation: RuntimeManagerOperation,
        required_state: RuntimeManagerState,
    ) -> None:
        self.current_state = current_state
        self.operation = operation
        self.required_state = required_state
        super().__init__(
            f"cannot {operation.value} runtime while {current_state.value}; "
            f"requires {required_state.value}"
        )


@dataclass(frozen=True, slots=True)
class RollbackFailure:
    """One resource shutdown failure observed during startup rollback."""

    identity: ResourceIdentity
    error: Exception


@dataclass(frozen=True, slots=True)
class ShutdownFailure:
    """One resource shutdown failure observed during normal shutdown."""

    identity: ResourceIdentity
    error: Exception


class RuntimeStartupError(RuntimeManagerError):
    """Raised after startup fails and rollback has been fully attempted."""

    def __init__(
        self,
        identity: ResourceIdentity,
        primary_failure: Exception,
        rollback_failures: tuple[RollbackFailure, ...],
    ) -> None:
        self.identity = identity
        self.primary_failure = primary_failure
        self.rollback_failures = rollback_failures
        super().__init__(f"runtime startup failed at resource {identity!s}")


class RuntimeShutdownError(RuntimeManagerError):
    """Raised after shutdown completes with one or more failures."""

    def __init__(self, failures: tuple[ShutdownFailure, ...]) -> None:
        self.failures = failures
        super().__init__(f"runtime shutdown completed with {len(failures)} failure(s)")
