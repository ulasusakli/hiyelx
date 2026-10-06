"""Typed errors for the local gRPC boundary and transport."""

from __future__ import annotations

from enum import Enum

from hiyelx.resources import ResourceIdentity
from hiyelx.runtime import RuntimeManagerState


class RpcBoundaryError(Exception):
    """Base class for failures owned by the gRPC adapter."""


class InvalidRpcIdentityError(RpcBoundaryError):
    """Raised when an RPC identity cannot form a ResourceIdentity."""

    def __init__(self, value: str) -> None:
        self.value = value
        super().__init__("resource identity must not be blank")


class ResourceNotMotorError(RpcBoundaryError):
    """Raised when an owned resource does not implement Motor."""

    def __init__(self, identity: ResourceIdentity) -> None:
        self.identity = identity
        super().__init__(f"resource {identity!s} is not a motor")


class RuntimeNotRunningError(RpcBoundaryError):
    """Raised when an RPC is attempted outside a running runtime."""

    def __init__(self, state: RuntimeManagerState) -> None:
        self.state = state
        super().__init__(f"runtime is not running while {state.value}")


class RpcTransportState(Enum):
    """Lifecycle state of only the gRPC transport."""

    NEW = "new"
    RUNNING = "running"
    STOPPED = "stopped"
    FAILED = "failed"


class RpcTransportError(RpcBoundaryError):
    """Base class for gRPC transport failures."""


class InvalidRpcBindAddressError(RpcTransportError):
    """Raised when a bind address is not a literal IPv4 loopback address."""

    def __init__(self, host: str) -> None:
        self.host = host
        super().__init__("gRPC transport requires an IPv4 loopback address")


class InvalidRpcPortError(RpcTransportError):
    """Raised when a requested TCP port is outside the valid range."""

    def __init__(self, port: object) -> None:
        self.port = port
        super().__init__("gRPC transport port must be an integer from 0 through 65535")


class InvalidRpcTransportStateError(RpcTransportError):
    """Raised when a transport operation is invalid in the current state."""

    def __init__(self, state: RpcTransportState, operation: str) -> None:
        self.state = state
        self.operation = operation
        super().__init__(f"cannot {operation} gRPC transport while {state.value}")


class RpcTransportBindingError(RpcTransportError):
    """Raised when gRPC cannot bind the requested loopback endpoint."""


class RpcTransportStartError(RpcTransportError):
    """Raised when the gRPC transport cannot complete startup."""


class RpcTransportStopError(RpcTransportError):
    """Raised when the gRPC transport cannot complete shutdown."""


class RpcTransportNotBoundError(RpcTransportError):
    """Raised when a selected port is requested before a successful bind."""
