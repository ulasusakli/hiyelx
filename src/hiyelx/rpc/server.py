"""Loopback-only asynchronous gRPC transport lifecycle."""

from __future__ import annotations

from ipaddress import IPv4Address, ip_address

import grpc

from hiyelx.rpc.errors import (
    InvalidRpcBindAddressError,
    InvalidRpcPortError,
    InvalidRpcTransportStateError,
    RpcTransportBindingError,
    RpcTransportNotBoundError,
    RpcTransportStartError,
    RpcTransportState,
    RpcTransportStopError,
)
from hiyelx.rpc.generated import motor_pb2_grpc
from hiyelx.rpc.motor_service import MotorService
from hiyelx.runtime import RuntimeManager


class MotorGrpcServer:
    """Own only a local MotorService transport, never the robot runtime."""

    def __init__(
        self,
        runtime: RuntimeManager,
        *,
        host: str = "127.0.0.1",
        port: int = 0,
    ) -> None:
        try:
            address = ip_address(host)
        except ValueError as error:
            raise InvalidRpcBindAddressError(host) from error
        if not isinstance(address, IPv4Address) or not address.is_loopback:
            raise InvalidRpcBindAddressError(host)
        if isinstance(port, bool) or not 0 <= port <= 65535:
            raise InvalidRpcPortError(port)

        self._runtime = runtime
        self._host = host
        self._requested_port = port
        self._state = RpcTransportState.NEW
        self._server: grpc.aio.Server | None = None
        self._bound_port: int | None = None

    @property
    def state(self) -> RpcTransportState:
        """Return the independent gRPC transport state."""
        return self._state

    @property
    def bound_port(self) -> int:
        """Return the selected port after a successful bind."""
        if self._bound_port is None:
            raise RpcTransportNotBoundError("gRPC transport has not bound a port")
        return self._bound_port

    @property
    def target(self) -> str:
        """Return the local channel target after a successful bind."""
        return f"{self._host}:{self.bound_port}"

    async def start_transport(self) -> None:
        """Start only the gRPC server on the configured loopback endpoint."""
        if self._state is not RpcTransportState.NEW:
            raise InvalidRpcTransportStateError(self._state, "start")

        server = grpc.aio.server()
        motor_pb2_grpc.add_MotorServiceServicer_to_server(MotorService(self._runtime), server)
        try:
            selected_port = server.add_insecure_port(
                f"{self._host}:{self._requested_port}"
            )
        except Exception as error:
            self._state = RpcTransportState.FAILED
            await server.stop(0)
            raise RpcTransportBindingError(
                "gRPC could not bind the loopback endpoint"
            ) from error
        if selected_port == 0:
            self._state = RpcTransportState.FAILED
            await server.stop(0)
            raise RpcTransportBindingError("gRPC could not bind the loopback endpoint")

        self._server = server
        self._bound_port = selected_port
        try:
            await server.start()
        except Exception as error:
            self._state = RpcTransportState.FAILED
            await server.stop(0)
            raise RpcTransportStartError("gRPC transport failed to start") from error
        self._state = RpcTransportState.RUNNING

    async def stop_transport(self) -> None:
        """Stop only the gRPC transport, leaving the runtime untouched."""
        if self._state is not RpcTransportState.RUNNING:
            raise InvalidRpcTransportStateError(self._state, "stop")
        server = self._server
        if server is None:
            self._state = RpcTransportState.FAILED
            raise RpcTransportStopError("gRPC transport server is unavailable")
        try:
            await server.stop(0)
        except Exception as error:
            self._state = RpcTransportState.FAILED
            raise RpcTransportStopError("gRPC transport failed to stop") from error
        self._state = RpcTransportState.STOPPED
