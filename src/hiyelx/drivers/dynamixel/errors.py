"""Typed domain-facing failures for the fixed XL430-W250-T driver."""

from dataclasses import dataclass

from hiyelx.components import MotorError
from hiyelx.resources import BackendUnavailableError, ResourceIdentity


class DynamixelDriverError(MotorError):
    """Base class for errors translated at the DYNAMIXEL HAL boundary."""

    def __init__(
        self,
        identity: ResourceIdentity,
        motor_id: int,
        operation: str,
        message: str,
    ) -> None:
        self.identity = identity
        self.motor_id = motor_id
        self.operation = operation
        self.startup_cleanup_failures: tuple[CleanupFailure, ...] = ()
        super().__init__(message)


class PortOpenError(DynamixelDriverError, BackendUnavailableError):
    """Raised when the configured serial port cannot be opened."""

    def __init__(self, identity: ResourceIdentity, motor_id: int) -> None:
        super().__init__(identity, motor_id, "open_port", "DYNAMIXEL port open failed")


class BaudRateConfigurationError(DynamixelDriverError, BackendUnavailableError):
    """Raised when the serial baud rate cannot be configured."""

    def __init__(self, identity: ResourceIdentity, motor_id: int, baud_rate: int) -> None:
        self.baud_rate = baud_rate
        super().__init__(
            identity,
            motor_id,
            "set_baud_rate",
            "DYNAMIXEL baud-rate configuration failed",
        )


class PingError(DynamixelDriverError, BackendUnavailableError):
    """Raised when the configured motor cannot be identified."""

    def __init__(self, identity: ResourceIdentity, motor_id: int) -> None:
        super().__init__(identity, motor_id, "ping", "DYNAMIXEL ping failed")


class UnexpectedModelError(DynamixelDriverError):
    """Raised when a responding device is not the fixed XL430 model."""

    def __init__(
        self,
        identity: ResourceIdentity,
        motor_id: int,
        expected_model_number: int,
        actual_model_number: int,
    ) -> None:
        self.expected_model_number = expected_model_number
        self.actual_model_number = actual_model_number
        super().__init__(
            identity,
            motor_id,
            "verify_model",
            "DYNAMIXEL model number does not match XL430-W250-T",
        )


class DeviceReportedError(DynamixelDriverError, BackendUnavailableError):
    """Raised when a status packet or hardware register reports an error."""

    def __init__(
        self,
        identity: ResourceIdentity,
        motor_id: int,
        operation: str,
        device_error: int,
        *,
        register_address: int | None = None,
    ) -> None:
        self.device_error = device_error
        self.register_address = register_address
        super().__init__(
            identity,
            motor_id,
            operation,
            "DYNAMIXEL device reported an error",
        )


class DynamixelCommunicationError(DynamixelDriverError, BackendUnavailableError):
    """Raised for a communication failure without leaking SDK objects."""

    def __init__(
        self,
        identity: ResourceIdentity,
        motor_id: int,
        operation: str,
        communication_result: int | None = None,
        *,
        register_address: int | None = None,
    ) -> None:
        self.communication_result = communication_result
        self.register_address = register_address
        super().__init__(
            identity,
            motor_id,
            operation,
            "DYNAMIXEL communication failed",
        )


class OperatingModeConfigurationError(DynamixelCommunicationError):
    """Raised when Velocity Control Mode cannot be configured."""


class TorqueOperationError(DynamixelCommunicationError):
    """Raised when torque enable or disable fails."""

    def __init__(
        self,
        identity: ResourceIdentity,
        motor_id: int,
        enabled: bool,
        communication_result: int | None = None,
    ) -> None:
        self.enabled = enabled
        super().__init__(
            identity,
            motor_id,
            "enable_torque" if enabled else "disable_torque",
            communication_result,
        )


class VelocityWriteError(DynamixelCommunicationError):
    """Raised when Goal Velocity cannot be written."""


class StateReadError(DynamixelCommunicationError):
    """Raised when a measured motor-state register cannot be read."""


class VelocityLimitError(DynamixelDriverError):
    """Raised before I/O when a command exceeds the configured software cap."""

    def __init__(
        self,
        identity: ResourceIdentity,
        motor_id: int,
        requested_velocity_rad_s: float,
        max_abs_velocity_rad_s: float,
    ) -> None:
        self.requested_velocity_rad_s = requested_velocity_rad_s
        self.max_abs_velocity_rad_s = max_abs_velocity_rad_s
        super().__init__(
            identity,
            motor_id,
            "validate_velocity",
            "motor command exceeds the configured software velocity limit",
        )


class VelocityRepresentationError(DynamixelDriverError):
    """Raised when a finite command cannot fit the XL430 velocity range."""


@dataclass(frozen=True, slots=True)
class CleanupFailure:
    """One ordered best-effort cleanup failure."""

    operation: str
    error: Exception


class ShutdownCleanupError(DynamixelDriverError, BackendUnavailableError):
    """Raised after all shutdown cleanup operations have been attempted."""

    def __init__(
        self,
        identity: ResourceIdentity,
        motor_id: int,
        failures: tuple[CleanupFailure, ...],
    ) -> None:
        self.failures = failures
        super().__init__(
            identity,
            motor_id,
            "shutdown_cleanup",
            f"DYNAMIXEL shutdown completed with {len(failures)} cleanup failure(s)",
        )
