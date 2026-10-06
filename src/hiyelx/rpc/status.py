"""Central deterministic mapping from domain failures to gRPC status."""

from __future__ import annotations

from dataclasses import dataclass

import grpc

from hiyelx.components import InvalidMotorCommandError, MotorUnavailableError
from hiyelx.resources import BackendUnavailableError, OperationDeadlineExceeded
from hiyelx.rpc.errors import (
    InvalidRpcIdentityError,
    ResourceNotMotorError,
    RuntimeNotRunningError,
)
from hiyelx.runtime import UnknownOwnedResourceError


@dataclass(frozen=True, slots=True)
class RpcStatus:
    """Stable status code and client-safe detail for one failure."""

    code: grpc.StatusCode
    detail: str


def status_for_error(error: Exception) -> RpcStatus:
    """Map an expected domain error, or conceal an unexpected one."""
    if isinstance(error, OperationDeadlineExceeded):
        return RpcStatus(grpc.StatusCode.DEADLINE_EXCEEDED, "operation deadline exceeded")
    if isinstance(error, InvalidRpcIdentityError):
        return RpcStatus(grpc.StatusCode.INVALID_ARGUMENT, "identity must not be blank")
    if isinstance(error, InvalidMotorCommandError):
        return RpcStatus(
            grpc.StatusCode.INVALID_ARGUMENT,
            "angular velocity must be finite",
        )
    if isinstance(error, UnknownOwnedResourceError):
        return RpcStatus(
            grpc.StatusCode.NOT_FOUND,
            f"resource '{error.identity!s}' was not found",
        )
    if isinstance(error, ResourceNotMotorError):
        return RpcStatus(
            grpc.StatusCode.FAILED_PRECONDITION,
            f"resource '{error.identity!s}' is not a motor",
        )
    if isinstance(error, MotorUnavailableError):
        return RpcStatus(
            grpc.StatusCode.FAILED_PRECONDITION,
            f"motor '{error.identity!s}' is not available",
        )
    if isinstance(error, RuntimeNotRunningError):
        return RpcStatus(grpc.StatusCode.UNAVAILABLE, "runtime is not running")
    if isinstance(error, BackendUnavailableError):
        return RpcStatus(grpc.StatusCode.UNAVAILABLE, "resource backend is unavailable")
    return RpcStatus(grpc.StatusCode.INTERNAL, "internal server error")
