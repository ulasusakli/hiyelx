"""Vendor-neutral resource identity, lifecycle, and health contracts."""

from hiyelx.resources._resource import (
    LIFECYCLE_TRANSITIONS,
    HealthStatus,
    InvalidLifecycleTransition,
    LifecycleState,
    Resource,
    ResourceHealth,
    ResourceIdentity,
    ResourceLifecycleError,
    ResourceShutdownError,
    ResourceStartupError,
)
from hiyelx.resources.reliability import (
    DEFAULT_OPERATION_DEADLINES,
    BackendUnavailableError,
    InvalidDeadlineError,
    OperationDeadlineExceeded,
    OperationDeadlinePolicy,
    OperationTimeoutDetails,
    ReliabilityError,
)

__all__ = [
    "LIFECYCLE_TRANSITIONS",
    "DEFAULT_OPERATION_DEADLINES",
    "BackendUnavailableError",
    "HealthStatus",
    "InvalidLifecycleTransition",
    "InvalidDeadlineError",
    "LifecycleState",
    "Resource",
    "ResourceHealth",
    "ResourceIdentity",
    "ResourceLifecycleError",
    "ResourceShutdownError",
    "ResourceStartupError",
    "OperationDeadlineExceeded",
    "OperationDeadlinePolicy",
    "OperationTimeoutDetails",
    "ReliabilityError",
]
