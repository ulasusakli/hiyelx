import pytest

from hiyelx.config import RuntimeConfig
from hiyelx.models import ModelRegistry
from hiyelx.rpc import (
    InvalidRpcBindAddressError,
    InvalidRpcPortError,
    InvalidRpcTransportStateError,
    MotorGrpcServer,
    RpcTransportNotBoundError,
    RpcTransportState,
)
from hiyelx.runtime import RuntimeManager, RuntimeManagerState


def _empty_runtime() -> RuntimeManager:
    return RuntimeManager(RuntimeConfig(schema_version="1", resources=[]), ModelRegistry())


@pytest.mark.parametrize("host", ["0.0.0.0", "192.168.1.10", "::1", "localhost"])
def test_non_ipv4_loopback_binding_is_rejected(host: str) -> None:
    with pytest.raises(InvalidRpcBindAddressError):
        MotorGrpcServer(_empty_runtime(), host=host)


@pytest.mark.parametrize("port", [-1, 65536, True])
def test_invalid_port_is_rejected(port: int) -> None:
    with pytest.raises(InvalidRpcPortError):
        MotorGrpcServer(_empty_runtime(), port=port)


def test_bound_port_is_unavailable_before_start() -> None:
    server = MotorGrpcServer(_empty_runtime())

    with pytest.raises(RpcTransportNotBoundError):
        _ = server.bound_port


@pytest.mark.asyncio
async def test_transport_lifecycle_does_not_control_runtime() -> None:
    runtime = _empty_runtime()
    server = MotorGrpcServer(runtime, port=0)

    await server.start_transport()
    try:
        assert server.state is RpcTransportState.RUNNING
        assert server.bound_port > 0
        assert runtime.state is RuntimeManagerState.NEW
        with pytest.raises(InvalidRpcTransportStateError):
            await server.start_transport()
    finally:
        await server.stop_transport()

    assert runtime.state is RuntimeManagerState.NEW
    assert server.state is RpcTransportState.STOPPED
    with pytest.raises(InvalidRpcTransportStateError):
        await server.stop_transport()
