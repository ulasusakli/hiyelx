import asyncio
from math import isclose

import pytest

from hiyelx.components import MotorCommand, MotorState, MotorUnavailableError
from hiyelx.drivers.dynamixel import (
    BaudRateConfigurationError,
    DeviceReportedError,
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
    XL430Motor,
    XL430MotorSettings,
)
from hiyelx.drivers.dynamixel.constants import (
    GOAL_VELOCITY_ADDRESS,
    POSITION_UNIT_RADIANS,
    PRESENT_POSITION_ADDRESS,
    PRESENT_VELOCITY_ADDRESS,
    VELOCITY_UNIT_RADIANS_PER_SECOND,
)
from hiyelx.drivers.dynamixel.conversion import (
    encode_signed_32,
    radians_per_second_to_raw,
)
from hiyelx.drivers.dynamixel.transport import (
    TransportCommunicationError,
    TransportDeviceError,
)
from hiyelx.resources import (
    LifecycleState,
    ResourceIdentity,
    ResourceShutdownError,
    ResourceStartupError,
)
from tests.unit.drivers.dynamixel.fake_transport import FakeDynamixelTransport

IDENTITY = ResourceIdentity("reference_motor")


def _motor(
    transport: FakeDynamixelTransport,
    *,
    max_velocity: float = 0.5,
) -> XL430Motor:
    return XL430Motor(
        IDENTITY,
        XL430MotorSettings(
            device="/dev/reference",
            max_abs_velocity_rad_s=max_velocity,
        ),
        transport,
    )


def test_construction_performs_no_transport_io() -> None:
    transport = FakeDynamixelTransport()
    motor = _motor(transport)

    assert transport.events == []
    assert motor.state is LifecycleState.CREATED


@pytest.mark.asyncio
async def test_startup_uses_exact_safe_order() -> None:
    transport = FakeDynamixelTransport()
    motor = _motor(transport)

    await motor.start()

    assert transport.events == [
        "open_port",
        "set_baud_rate:57600",
        "ping:1",
        "write:1:64:1:0",
        "write:1:11:1:1",
        "write:1:104:4:0",
        "read:1:70:1",
        "write:1:64:1:1",
    ]
    assert motor.state is LifecycleState.RUNNING


@pytest.mark.asyncio
async def test_unexpected_model_is_rejected_before_torque_enable() -> None:
    transport = FakeDynamixelTransport()
    transport.model_number = 999
    motor = _motor(transport)

    with pytest.raises(ResourceStartupError) as caught:
        await motor.start()

    assert isinstance(caught.value.__cause__, UnexpectedModelError)
    assert caught.value.__cause__.actual_model_number == 999
    assert "write:1:64:1:1" not in transport.events
    assert transport.events[-3:] == [
        "write:1:104:4:0",
        "write:1:64:1:0",
        "close_port",
    ]


@pytest.mark.parametrize(
    ("failure_key", "expected_error"),
    [
        ("open_port", PortOpenError),
        ("set_baud_rate", BaudRateConfigurationError),
        ("ping", PingError),
        ("write:11", OperatingModeConfigurationError),
        ("write:104", VelocityWriteError),
        ("read:70", StateReadError),
    ],
)
@pytest.mark.asyncio
async def test_startup_stage_failure_is_typed_and_runs_cleanup(
    failure_key: str,
    expected_error: type[Exception],
) -> None:
    transport = FakeDynamixelTransport()
    transport.fail_next(failure_key)
    motor = _motor(transport)

    with pytest.raises(ResourceStartupError) as caught:
        await motor.start()

    assert isinstance(caught.value.__cause__, expected_error)
    assert caught.value.__cause__.__cause__ is not None
    assert transport.events[-3:] == [
        "write:1:104:4:0",
        "write:1:64:1:0",
        "close_port",
    ]
    assert motor.state is LifecycleState.FAILED


@pytest.mark.parametrize(
    ("failure_index", "expected_error"),
    [(0, TorqueOperationError), (1, TorqueOperationError)],
)
@pytest.mark.asyncio
async def test_startup_torque_failures_are_typed(
    failure_index: int,
    expected_error: type[Exception],
) -> None:
    transport = FakeDynamixelTransport()
    if failure_index == 0:
        transport.fail_next("write:64")
    else:
        transport.failures["write:64"] = [None, RuntimeError("enable torque")]
    motor = _motor(transport)

    with pytest.raises(ResourceStartupError) as caught:
        await motor.start()

    assert isinstance(caught.value.__cause__, expected_error)


@pytest.mark.asyncio
async def test_hardware_error_status_prevents_torque_enable() -> None:
    transport = FakeDynamixelTransport()
    transport.registers[70] = 0x04
    motor = _motor(transport)

    with pytest.raises(ResourceStartupError) as caught:
        await motor.start()

    assert isinstance(caught.value.__cause__, DeviceReportedError)
    assert caught.value.__cause__.device_error == 0x04
    assert "write:1:64:1:1" not in transport.events


@pytest.mark.asyncio
async def test_startup_cleanup_failures_are_ordered_without_hiding_primary() -> None:
    transport = FakeDynamixelTransport()
    transport.fail_next("ping", ValueError("primary"))
    transport.fail_next("write:104", RuntimeError("zero"))
    transport.fail_next("write:64", RuntimeError("torque"))
    transport.fail_next("close_port", RuntimeError("close"))
    motor = _motor(transport)

    with pytest.raises(ResourceStartupError) as caught:
        await motor.start()

    primary = caught.value.__cause__
    assert isinstance(primary, PingError)
    assert isinstance(primary.__cause__, ValueError)
    assert tuple(failure.operation for failure in primary.startup_cleanup_failures) == (
        "write_zero_velocity",
        "disable_torque",
        "close_port",
    )


@pytest.mark.asyncio
async def test_commands_write_positive_negative_and_zero_velocity() -> None:
    transport = FakeDynamixelTransport()
    motor = _motor(transport)
    await motor.start()
    transport.events.clear()

    await motor.apply_command(MotorCommand(VELOCITY_UNIT_RADIANS_PER_SECOND))
    await motor.apply_command(MotorCommand(-VELOCITY_UNIT_RADIANS_PER_SECOND))
    await motor.stop()

    assert transport.events == [
        "write:1:104:4:1",
        f"write:1:104:4:{encode_signed_32(-1)}",
        "write:1:104:4:0",
    ]


@pytest.mark.asyncio
async def test_velocity_limit_rejects_before_transport_io() -> None:
    transport = FakeDynamixelTransport()
    motor = _motor(transport, max_velocity=0.3)
    await motor.start()
    transport.events.clear()

    with pytest.raises(VelocityLimitError):
        await motor.apply_command(MotorCommand(0.3001))

    assert transport.events == []


@pytest.mark.asyncio
async def test_velocity_limit_boundary_is_accepted() -> None:
    transport = FakeDynamixelTransport()
    motor = _motor(transport, max_velocity=0.3)
    await motor.start()
    transport.events.clear()

    await motor.apply_command(MotorCommand(-0.3))

    assert transport.events == [
        f"write:1:104:4:{encode_signed_32(radians_per_second_to_raw(-0.3))}"
    ]


@pytest.mark.asyncio
async def test_unrepresentable_finite_velocity_is_rejected_before_io() -> None:
    transport = FakeDynamixelTransport()
    motor = _motor(transport, max_velocity=100.0)
    await motor.start()
    transport.events.clear()

    with pytest.raises(VelocityRepresentationError):
        await motor.apply_command(MotorCommand(1024 * VELOCITY_UNIT_RADIANS_PER_SECOND))

    assert transport.events == []


@pytest.mark.asyncio
async def test_state_reads_measured_position_and_velocity() -> None:
    transport = FakeDynamixelTransport()
    transport.registers[PRESENT_POSITION_ADDRESS] = encode_signed_32(-10)
    transport.registers[PRESENT_VELOCITY_ADDRESS] = encode_signed_32(3)
    motor = _motor(transport)
    await motor.start()
    transport.events.clear()

    state = await motor.read_state()

    assert isinstance(state, MotorState)
    assert isclose(state.angular_position_radians, -10 * POSITION_UNIT_RADIANS)
    assert isclose(
        state.angular_velocity_radians_per_second,
        3 * VELOCITY_UNIT_RADIANS_PER_SECOND,
    )
    assert transport.events == ["read:1:132:4", "read:1:128:4"]


@pytest.mark.parametrize("address", [PRESENT_POSITION_ADDRESS, PRESENT_VELOCITY_ADDRESS])
@pytest.mark.asyncio
async def test_state_read_communication_failure_is_translated(address: int) -> None:
    transport = FakeDynamixelTransport()
    motor = _motor(transport)
    await motor.start()
    failure = TransportCommunicationError("read", -1001, address)
    transport.fail_next(f"read:{address}", failure)

    with pytest.raises(StateReadError) as caught:
        await motor.read_state()

    assert caught.value.communication_result == -1001
    assert caught.value.register_address == address
    assert caught.value.__cause__ is failure


@pytest.mark.asyncio
async def test_command_transport_failure_is_translated_and_chained() -> None:
    transport = FakeDynamixelTransport()
    motor = _motor(transport)
    await motor.start()
    failure = TransportCommunicationError("write", -1001, GOAL_VELOCITY_ADDRESS)
    transport.fail_next("write:104", failure)

    with pytest.raises(VelocityWriteError) as caught:
        await motor.apply_command(MotorCommand(0.1))

    assert caught.value.communication_result == -1001
    assert caught.value.__cause__ is failure


@pytest.mark.asyncio
async def test_device_error_is_translated_without_sdk_object() -> None:
    transport = FakeDynamixelTransport()
    motor = _motor(transport)
    await motor.start()
    failure = TransportDeviceError("write", 0x40, GOAL_VELOCITY_ADDRESS)
    transport.fail_next("write:104", failure)

    with pytest.raises(DeviceReportedError) as caught:
        await motor.apply_command(MotorCommand(0.1))

    assert caught.value.device_error == 0x40
    assert caught.value.register_address == GOAL_VELOCITY_ADDRESS
    assert caught.value.__cause__ is failure


@pytest.mark.asyncio
async def test_shutdown_uses_exact_safe_order() -> None:
    transport = FakeDynamixelTransport()
    motor = _motor(transport)
    await motor.start()
    transport.events.clear()

    await motor.shutdown()

    assert transport.events == [
        "write:1:104:4:0",
        "write:1:64:1:0",
        "close_port",
    ]
    assert motor.state is LifecycleState.STOPPED


@pytest.mark.asyncio
async def test_shutdown_continues_and_reports_every_failure_in_order() -> None:
    transport = FakeDynamixelTransport()
    motor = _motor(transport)
    await motor.start()
    transport.events.clear()
    transport.fail_next("write:104", RuntimeError("zero"))
    transport.fail_next("write:64", RuntimeError("torque"))
    transport.fail_next("close_port", RuntimeError("close"))

    with pytest.raises(ResourceShutdownError) as caught:
        await motor.shutdown()

    cleanup_error = caught.value.__cause__
    assert isinstance(cleanup_error, ShutdownCleanupError)
    assert tuple(failure.operation for failure in cleanup_error.failures) == (
        "write_zero_velocity",
        "disable_torque",
        "close_port",
    )
    assert transport.events == [
        "write:1:104:4:0",
        "write:1:64:1:0",
        "close_port",
    ]
    assert motor.state is LifecycleState.FAILED


@pytest.mark.asyncio
async def test_transport_access_is_never_concurrent() -> None:
    transport = FakeDynamixelTransport()
    motor = _motor(transport)
    await motor.start()
    transport.max_concurrent_calls = 0
    transport.delay_seconds = 0.01

    await asyncio.gather(
        motor.read_state(),
        motor.apply_command(MotorCommand(0.1)),
        motor.read_state(),
    )

    assert transport.max_concurrent_calls == 1


@pytest.mark.asyncio
async def test_existing_motor_lifecycle_guard_remains_in_force() -> None:
    transport = FakeDynamixelTransport()
    motor = _motor(transport)

    with pytest.raises(MotorUnavailableError):
        await motor.apply_command(MotorCommand.zero_velocity())

    await motor.start()
    await motor.shutdown()

    with pytest.raises(MotorUnavailableError):
        await motor.stop()
