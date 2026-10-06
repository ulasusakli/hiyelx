"""Concrete XL430-W250-T Motor implementation for one actuator per port."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from contextlib import suppress

from hiyelx.components import Motor, MotorCommand, MotorState
from hiyelx.drivers.dynamixel.constants import (
    EXPECTED_MODEL_NUMBER,
    GOAL_VELOCITY_ADDRESS,
    GOAL_VELOCITY_SIZE,
    HARDWARE_ERROR_STATUS_ADDRESS,
    HARDWARE_ERROR_STATUS_SIZE,
    OPERATING_MODE_ADDRESS,
    OPERATING_MODE_SIZE,
    PRESENT_POSITION_ADDRESS,
    PRESENT_POSITION_SIZE,
    PRESENT_VELOCITY_ADDRESS,
    PRESENT_VELOCITY_SIZE,
    TORQUE_DISABLED,
    TORQUE_ENABLE_ADDRESS,
    TORQUE_ENABLE_SIZE,
    TORQUE_ENABLED,
    VELOCITY_CONTROL_MODE,
)
from hiyelx.drivers.dynamixel.conversion import (
    VelocityNotRepresentableError,
    encode_signed_32,
    radians_per_second_to_raw,
    raw_position_to_radians,
    raw_velocity_to_radians_per_second,
)
from hiyelx.drivers.dynamixel.errors import (
    BaudRateConfigurationError,
    CleanupFailure,
    DeviceReportedError,
    DynamixelCommunicationError,
    DynamixelDriverError,
    OperatingModeConfigurationError,
    PingError,
    PortOpenError,
    ShutdownCleanupError,
    StateReadError,
    TorqueOperationError,
    UnexpectedModelError,
    VelocityLimitError,
    VelocityRepresentationError,
    VelocityWriteError,
)
from hiyelx.drivers.dynamixel.settings import XL430MotorSettings
from hiyelx.drivers.dynamixel.transport import (
    DynamixelTransport,
    SdkDynamixelTransport,
    TransportCommunicationError,
    TransportDeviceError,
)
from hiyelx.resources import (
    DEFAULT_OPERATION_DEADLINES,
    OperationDeadlineExceeded,
    OperationDeadlinePolicy,
    OperationTimeoutDetails,
    ResourceIdentity,
)


class XL430Motor(Motor):
    """DYNAMIXEL XL430-W250-T backend preserving the Motor API."""

    def __init__(
        self,
        identity: ResourceIdentity,
        settings: XL430MotorSettings,
        transport: DynamixelTransport | None = None,
        *,
        deadline_policy: OperationDeadlinePolicy = DEFAULT_OPERATION_DEADLINES,
    ) -> None:
        super().__init__(identity, deadline_policy=deadline_policy)
        self._settings = settings
        self._transport = transport or SdkDynamixelTransport(settings.device)
        self._operation_lock = asyncio.Lock()
        self._transport_lock = asyncio.Lock()

    @property
    def settings(self) -> XL430MotorSettings:
        """Return immutable validated settings without SDK objects."""
        return self._settings

    async def _on_start(self) -> None:
        async with self._operation_lock:
            try:
                await self._open_port()
                await self._set_baud_rate()
                model_number = await self._ping()
                if model_number != EXPECTED_MODEL_NUMBER:
                    raise UnexpectedModelError(
                        self.identity,
                        self._settings.motor_id,
                        EXPECTED_MODEL_NUMBER,
                        model_number,
                    )
                await self._set_torque(enabled=False)
                await self._set_velocity_control_mode()
                await self._write_goal_velocity_raw(0)
                await self._check_hardware_error_status()
                await self._set_torque(enabled=True)
            except Exception as primary_failure:
                cleanup_failures = await self._cleanup_locked()
                if isinstance(primary_failure, DynamixelDriverError):
                    primary_failure.startup_cleanup_failures = cleanup_failures
                raise

    async def _on_shutdown(self) -> None:
        async with self._operation_lock:
            failures = await self._cleanup_locked()
        if failures:
            error = ShutdownCleanupError(
                self.identity,
                self._settings.motor_id,
                failures,
            )
            raise error from failures[0].error

    async def _apply_command(self, command: MotorCommand) -> None:
        velocity = command.angular_velocity_radians_per_second
        if abs(velocity) > self._settings.max_abs_velocity_rad_s:
            raise VelocityLimitError(
                self.identity,
                self._settings.motor_id,
                velocity,
                self._settings.max_abs_velocity_rad_s,
            )
        try:
            raw_velocity = radians_per_second_to_raw(velocity)
        except VelocityNotRepresentableError as error:
            raise VelocityRepresentationError(
                self.identity,
                self._settings.motor_id,
                "convert_velocity",
                "motor command cannot be represented safely by the XL430",
            ) from error
        async with self._operation_lock:
            await self._write_goal_velocity_raw(raw_velocity)

    async def _read_state(self) -> MotorState:
        async with self._operation_lock:
            raw_position = await self._read_state_register(
                PRESENT_POSITION_ADDRESS, PRESENT_POSITION_SIZE
            )
            raw_velocity = await self._read_state_register(
                PRESENT_VELOCITY_ADDRESS, PRESENT_VELOCITY_SIZE
            )
        return MotorState(
            angular_position_radians=raw_position_to_radians(raw_position),
            angular_velocity_radians_per_second=raw_velocity_to_radians_per_second(raw_velocity),
        )

    async def _open_port(self) -> None:
        await self._run_transport(
            self._transport.open_port,
            lambda _result: PortOpenError(self.identity, self._settings.motor_id),
        )

    async def _set_baud_rate(self) -> None:
        await self._run_transport(
            lambda: self._transport.set_baud_rate(self._settings.baud_rate),
            lambda _result: BaudRateConfigurationError(
                self.identity,
                self._settings.motor_id,
                self._settings.baud_rate,
            ),
        )

    async def _ping(self) -> int:
        return await self._run_transport(
            lambda: self._transport.ping(self._settings.motor_id),
            lambda _result: PingError(self.identity, self._settings.motor_id),
        )

    async def _set_torque(self, *, enabled: bool) -> None:
        value = TORQUE_ENABLED if enabled else TORQUE_DISABLED
        await self._write_register(
            TORQUE_ENABLE_ADDRESS,
            TORQUE_ENABLE_SIZE,
            value,
            lambda result: TorqueOperationError(
                self.identity,
                self._settings.motor_id,
                enabled,
                result,
            ),
        )

    async def _set_velocity_control_mode(self) -> None:
        await self._write_register(
            OPERATING_MODE_ADDRESS,
            OPERATING_MODE_SIZE,
            VELOCITY_CONTROL_MODE,
            lambda result: OperatingModeConfigurationError(
                self.identity,
                self._settings.motor_id,
                "configure_operating_mode",
                result,
                register_address=OPERATING_MODE_ADDRESS,
            ),
        )

    async def _write_goal_velocity_raw(self, signed_raw_velocity: int) -> None:
        encoded = encode_signed_32(signed_raw_velocity)
        await self._write_register(
            GOAL_VELOCITY_ADDRESS,
            GOAL_VELOCITY_SIZE,
            encoded,
            lambda result: VelocityWriteError(
                self.identity,
                self._settings.motor_id,
                "write_goal_velocity",
                result,
                register_address=GOAL_VELOCITY_ADDRESS,
            ),
        )

    async def _check_hardware_error_status(self) -> None:
        status = await self._read_register(
            HARDWARE_ERROR_STATUS_ADDRESS,
            HARDWARE_ERROR_STATUS_SIZE,
            lambda result: StateReadError(
                self.identity,
                self._settings.motor_id,
                "read_hardware_error_status",
                result,
                register_address=HARDWARE_ERROR_STATUS_ADDRESS,
            ),
        )
        if status != 0:
            raise DeviceReportedError(
                self.identity,
                self._settings.motor_id,
                "check_hardware_error_status",
                status,
                register_address=HARDWARE_ERROR_STATUS_ADDRESS,
            )

    async def _read_state_register(self, address: int, size: int) -> int:
        return await self._read_register(
            address,
            size,
            lambda result: StateReadError(
                self.identity,
                self._settings.motor_id,
                "read_motor_state",
                result,
                register_address=address,
            ),
        )

    async def _read_register(
        self,
        address: int,
        size: int,
        error_factory: Callable[[int | None], DynamixelDriverError],
    ) -> int:
        return await self._run_transport(
            lambda: self._transport.read(self._settings.motor_id, address, size),
            error_factory,
            register_address=address,
        )

    async def _write_register(
        self,
        address: int,
        size: int,
        value: int,
        error_factory: Callable[[int | None], DynamixelDriverError],
    ) -> None:
        await self._run_transport(
            lambda: self._transport.write(self._settings.motor_id, address, size, value),
            error_factory,
            register_address=address,
        )

    async def _close_port(self) -> None:
        await self._run_transport(
            self._transport.close_port,
            lambda result: DynamixelCommunicationError(
                self.identity,
                self._settings.motor_id,
                "close_port",
                result,
            ),
        )

    async def _cleanup_locked(self) -> tuple[CleanupFailure, ...]:
        failures: list[CleanupFailure] = []
        actions = (
            ("write_zero_velocity", lambda: self._write_goal_velocity_raw(0)),
            ("disable_torque", lambda: self._set_torque(enabled=False)),
            ("close_port", self._close_port),
        )
        for operation, action in actions:
            try:
                await action()
            except Exception as error:
                failures.append(CleanupFailure(operation, error))
        return tuple(failures)

    async def _run_transport[ResultT](
        self,
        operation: Callable[[], ResultT],
        error_factory: Callable[[int | None], DynamixelDriverError],
        *,
        register_address: int | None = None,
    ) -> ResultT:
        runner = asyncio.create_task(self._execute_transport(operation))
        try:
            async with asyncio.timeout(
                self.deadline_policy.transport_operation_seconds
            ):
                return await asyncio.shield(runner)
        except TimeoutError as error:
            runner.cancel()
            runner.add_done_callback(self._consume_transport_task)
            details = OperationTimeoutDetails(
                identity=self.identity,
                operation=self._transport_operation_name(register_address),
                configured_timeout_seconds=(
                    self.deadline_policy.transport_operation_seconds
                ),
                lifecycle_state=self.state,
            )
            raise OperationDeadlineExceeded(details) from error
        except asyncio.CancelledError:
            runner.cancel()
            runner.add_done_callback(self._consume_transport_task)
            raise
        except TransportDeviceError as error:
            translated = DeviceReportedError(
                self.identity,
                self._settings.motor_id,
                error.operation,
                error.device_error,
                register_address=(error.address if error.address is not None else register_address),
            )
            raise translated from error
        except TransportCommunicationError as error:
            raise error_factory(error.communication_result) from error
        except Exception as error:
            raise error_factory(None) from error

    async def _execute_transport[ResultT](
        self,
        operation: Callable[[], ResultT],
    ) -> ResultT:
        async with self._transport_lock:
            worker = asyncio.create_task(asyncio.to_thread(operation))
            try:
                return await asyncio.shield(worker)
            except asyncio.CancelledError:
                with suppress(Exception):
                    await asyncio.shield(worker)
                raise

    @staticmethod
    def _consume_transport_task(task: asyncio.Task[object]) -> None:
        with suppress(BaseException):
            task.result()

    @staticmethod
    def _transport_operation_name(register_address: int | None) -> str:
        if register_address == GOAL_VELOCITY_ADDRESS:
            return "write_goal_velocity"
        if register_address in {PRESENT_POSITION_ADDRESS, PRESENT_VELOCITY_ADDRESS}:
            return "read_motor_state"
        return "transport_operation"
