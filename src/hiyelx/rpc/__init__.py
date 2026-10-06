"""Versioned local gRPC adapter and loopback transport."""

from hiyelx.rpc.errors import (
    InvalidRpcBindAddressError,
    InvalidRpcIdentityError,
    InvalidRpcPortError,
    InvalidRpcTransportStateError,
    ResourceNotMotorError,
    RpcBoundaryError,
    RpcTransportBindingError,
    RpcTransportError,
    RpcTransportNotBoundError,
    RpcTransportStartError,
    RpcTransportState,
    RpcTransportStopError,
    RuntimeNotRunningError,
)
from hiyelx.rpc.motor_service import MotorService
from hiyelx.rpc.server import MotorGrpcServer
from hiyelx.rpc.status import RpcStatus, status_for_error

__all__ = [
    "InvalidRpcBindAddressError",
    "InvalidRpcIdentityError",
    "InvalidRpcPortError",
    "InvalidRpcTransportStateError",
    "MotorGrpcServer",
    "MotorService",
    "ResourceNotMotorError",
    "RpcBoundaryError",
    "RpcStatus",
    "RpcTransportBindingError",
    "RpcTransportError",
    "RpcTransportNotBoundError",
    "RpcTransportStartError",
    "RpcTransportState",
    "RpcTransportStopError",
    "RuntimeNotRunningError",
    "status_for_error",
]
