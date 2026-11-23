import pytest

from hiyelx.components import Motor, MotorCommand, MotorState
from hiyelx.core import (
    Component,
    ComponentCapability,
    ComponentCategory,
)
from hiyelx.resources import (
    LifecycleState,
    ResourceIdentity,
)


class DummySensor(Component):
    """A minimal non-actuator component for testing."""

    def __init__(self, identity: ResourceIdentity) -> None:
        super().__init__(
            identity,
            category=ComponentCategory.FEEDBACK,
            capabilities=(ComponentCapability.HAS_ENCODER_TICKS,),
        )


class DummyMotor(Motor):
    """A minimal motor implementation for testing."""

    def __init__(self, identity: ResourceIdentity) -> None:
        super().__init__(identity)
        self.applied_velocities: list[float] = []

    async def _apply_command(self, command: MotorCommand) -> None:
        self.applied_velocities.append(command.angular_velocity_radians_per_second)

    async def _read_state(self) -> MotorState:
        return MotorState(angular_position_radians=0.0, angular_velocity_radians_per_second=0.0)


def test_component_category_and_capabilities() -> None:
    sensor = DummySensor(ResourceIdentity("encoder_1"))

    assert sensor.identity == ResourceIdentity("encoder_1")
    assert sensor.category == ComponentCategory.FEEDBACK
    assert sensor.capabilities == frozenset({ComponentCapability.HAS_ENCODER_TICKS})
    assert sensor.has_capability(ComponentCapability.HAS_ENCODER_TICKS)
    assert not sensor.has_capability(ComponentCapability.CAN_SET_VELOCITY)
    assert sensor.state == LifecycleState.CREATED


@pytest.mark.asyncio
async def test_component_safe_stop_default_noop() -> None:
    sensor = DummySensor(ResourceIdentity("encoder_1"))
    await sensor.safe_stop()  # Should not raise


def test_motor_inherits_component() -> None:
    motor = DummyMotor(ResourceIdentity("drive_motor"))

    assert isinstance(motor, Component)
    assert motor.category == ComponentCategory.ACTUATOR
    assert motor.has_capability(ComponentCapability.CAN_SET_VELOCITY)
    assert motor.has_capability(ComponentCapability.HAS_ANGULAR_POSITION)
    assert motor.has_capability(ComponentCapability.HAS_ANGULAR_VELOCITY)


@pytest.mark.asyncio
async def test_motor_safe_stop_stops_running_motor() -> None:
    motor = DummyMotor(ResourceIdentity("drive_motor"))
    await motor.start()
    assert motor.state == LifecycleState.RUNNING

    await motor.apply_command(MotorCommand(angular_velocity_radians_per_second=5.0))
    assert motor.applied_velocities[-1] == 5.0

    await motor.safe_stop()
    assert motor.applied_velocities[-1] == 0.0


@pytest.mark.asyncio
async def test_motor_safe_stop_noop_when_not_running() -> None:
    motor = DummyMotor(ResourceIdentity("drive_motor"))
    assert motor.state == LifecycleState.CREATED

    await motor.safe_stop()
    assert motor.applied_velocities == []
