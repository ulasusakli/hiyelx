"""Typed transport seam and isolated DYNAMIXEL SDK adapter."""

from __future__ import annotations

from typing import Protocol, cast

from hiyelx.drivers.dynamixel.constants import PROTOCOL_VERSION


class DynamixelTransport(Protocol):
    """Small blocking transport contract consumed by the async motor driver."""

    def open_port(self) -> None: ...

    def set_baud_rate(self, baud_rate: int) -> None: ...

    def ping(self, motor_id: int) -> int: ...

    def read(self, motor_id: int, address: int, size: int) -> int: ...

    def write(self, motor_id: int, address: int, size: int, value: int) -> None: ...

    def close_port(self) -> None: ...


class DynamixelTransportError(Exception):
    """Internal base error produced at the SDK boundary."""


class TransportPortOpenError(DynamixelTransportError):
    """Internal false result from PortHandler.openPort."""


class TransportBaudRateError(DynamixelTransportError):
    """Internal false result from PortHandler.setBaudRate."""


class TransportCommunicationError(DynamixelTransportError):
    """Internal SDK communication-result failure."""

    def __init__(
        self,
        operation: str,
        communication_result: int,
        address: int | None = None,
    ) -> None:
        self.operation = operation
        self.communication_result = communication_result
        self.address = address
        super().__init__("DYNAMIXEL SDK communication result was not successful")


class TransportDeviceError(DynamixelTransportError):
    """Internal device error byte returned by a status packet."""

    def __init__(self, operation: str, device_error: int, address: int | None = None) -> None:
        self.operation = operation
        self.device_error = device_error
        self.address = address
        super().__init__("DYNAMIXEL status packet contains a device error")


class _SdkPort(Protocol):
    def openPort(self) -> bool: ...

    def setBaudRate(self, baud_rate: int) -> bool: ...

    def closePort(self) -> None: ...


class _SdkPacket(Protocol):
    def ping(self, port: _SdkPort, motor_id: int) -> tuple[int, int, int]: ...

    def read1ByteTxRx(
        self, port: _SdkPort, motor_id: int, address: int
    ) -> tuple[int, int, int]: ...

    def read2ByteTxRx(
        self, port: _SdkPort, motor_id: int, address: int
    ) -> tuple[int, int, int]: ...

    def read4ByteTxRx(
        self, port: _SdkPort, motor_id: int, address: int
    ) -> tuple[int, int, int]: ...

    def write1ByteTxRx(
        self, port: _SdkPort, motor_id: int, address: int, value: int
    ) -> tuple[int, int]: ...

    def write2ByteTxRx(
        self, port: _SdkPort, motor_id: int, address: int, value: int
    ) -> tuple[int, int]: ...

    def write4ByteTxRx(
        self, port: _SdkPort, motor_id: int, address: int, value: int
    ) -> tuple[int, int]: ...


class _SdkModule(Protocol):
    COMM_SUCCESS: int

    def PortHandler(self, device: str) -> _SdkPort: ...

    def PacketHandler(self, protocol_version: float) -> _SdkPacket: ...


def _load_sdk() -> _SdkModule:
    # The untyped vendor package is imported only at the concrete transport boundary.
    import dynamixel_sdk  # pyright: ignore[reportMissingTypeStubs]

    return cast(_SdkModule, cast(object, dynamixel_sdk))


class SdkDynamixelTransport:
    """Blocking Protocol 2.0 adapter. Construction itself performs no I/O."""

    def __init__(self, device: str) -> None:
        sdk = _load_sdk()
        self._communication_success = sdk.COMM_SUCCESS
        self._port = sdk.PortHandler(device)
        self._packet = sdk.PacketHandler(PROTOCOL_VERSION)

    def open_port(self) -> None:
        if not self._port.openPort():
            raise TransportPortOpenError("DYNAMIXEL SDK could not open the port")

    def set_baud_rate(self, baud_rate: int) -> None:
        if not self._port.setBaudRate(baud_rate):
            raise TransportBaudRateError("DYNAMIXEL SDK could not set the baud rate")

    def ping(self, motor_id: int) -> int:
        model_number, communication_result, device_error = self._packet.ping(self._port, motor_id)
        self._check_result("ping", communication_result, device_error)
        return model_number

    def read(self, motor_id: int, address: int, size: int) -> int:
        readers = {
            1: self._packet.read1ByteTxRx,
            2: self._packet.read2ByteTxRx,
            4: self._packet.read4ByteTxRx,
        }
        try:
            reader = readers[size]
        except KeyError as error:
            raise ValueError("DYNAMIXEL register size must be 1, 2, or 4 bytes") from error
        value, communication_result, device_error = reader(self._port, motor_id, address)
        self._check_result("read", communication_result, device_error, address)
        return value

    def write(self, motor_id: int, address: int, size: int, value: int) -> None:
        writers = {
            1: self._packet.write1ByteTxRx,
            2: self._packet.write2ByteTxRx,
            4: self._packet.write4ByteTxRx,
        }
        try:
            writer = writers[size]
        except KeyError as error:
            raise ValueError("DYNAMIXEL register size must be 1, 2, or 4 bytes") from error
        communication_result, device_error = writer(self._port, motor_id, address, value)
        self._check_result("write", communication_result, device_error, address)

    def close_port(self) -> None:
        self._port.closePort()

    def _check_result(
        self,
        operation: str,
        communication_result: int,
        device_error: int,
        address: int | None = None,
    ) -> None:
        if communication_result != self._communication_success:
            raise TransportCommunicationError(operation, communication_result, address)
        if device_error != 0:
            raise TransportDeviceError(operation, device_error, address)
