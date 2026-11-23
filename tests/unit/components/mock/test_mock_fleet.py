import pytest

from hiyelx.components.mock import (
    MockCamera,
    MockEncoder,
    MockIMU,
    MockMotor,
    register_mock_components,
)
from hiyelx.config.v2.models import ComponentDefinition
from hiyelx.core import (
    ComponentCapability,
    ComponentCategory,
    ComponentRegistry,
)
from hiyelx.resources import ResourceIdentity


def test_mock_motor() -> None:
    motor = MockMotor(ResourceIdentity("motor_1"), max_rpm=200.0)

    assert motor.identity == ResourceIdentity("motor_1")
    assert motor.category == ComponentCategory.ACTUATOR
    assert motor.max_rpm == 200.0
    assert motor.has_capability(ComponentCapability.CAN_SET_VELOCITY)


def test_mock_encoder() -> None:
    encoder = MockEncoder(ResourceIdentity("encoder_1"), resolution_cpr=2048)

    assert encoder.identity == ResourceIdentity("encoder_1")
    assert encoder.category == ComponentCategory.FEEDBACK
    assert encoder.resolution_cpr == 2048
    assert encoder.ticks == 0
    assert encoder.position_radians == 0.0

    encoder.set_ticks(1024)
    assert encoder.ticks == 1024
    assert pytest.approx(encoder.position_radians) == 3.141592653589793

    encoder.update_ticks(512)
    assert encoder.ticks == 1536


def test_mock_camera() -> None:
    camera = MockCamera(ResourceIdentity("camera_1"), width=320, height=240, fps=15)

    assert camera.identity == ResourceIdentity("camera_1")
    assert camera.category == ComponentCategory.VISION
    assert camera.resolution == (320, 240)
    assert camera.fps == 15
    assert camera.frame_count == 0

    frame_bytes = camera.capture_frame()
    assert len(frame_bytes) == 320 * 240 * 3
    assert camera.frame_count == 1


def test_mock_imu() -> None:
    imu = MockIMU(ResourceIdentity("imu_1"), sample_rate_hz=50.0)

    assert imu.identity == ResourceIdentity("imu_1")
    assert imu.category == ComponentCategory.SPATIAL
    assert imu.sample_rate_hz == 50.0
    assert imu.orientation == (0.0, 0.0, 0.0, 1.0)
    assert imu.linear_acceleration == (0.0, 0.0, 9.81)

    imu.set_orientation(0.0, 0.7071, 0.0, 0.7071)
    assert imu.orientation == (0.0, 0.7071, 0.0, 0.7071)

    imu.set_motion((0.1, 0.2, 0.3), (0.0, 0.0, 10.0))
    assert imu.angular_velocity == (0.1, 0.2, 0.3)
    assert imu.linear_acceleration == (0.0, 0.0, 10.0)


def test_register_mock_components_and_create() -> None:
    registry = ComponentRegistry()
    register_mock_components(registry)

    assert "mock.motor" in registry.registered_models()
    assert "mock.encoder" in registry.registered_models()
    assert "mock.camera" in registry.registered_models()
    assert "mock.imu" in registry.registered_models()

    motor_def = ComponentDefinition(
        id=ResourceIdentity("m1"),
        category=ComponentCategory.ACTUATOR,
        model="mock.motor",
        settings={"max_rpm": 250},
    )
    motor = registry.create(motor_def)
    assert isinstance(motor, MockMotor)
    assert motor.max_rpm == 250.0

    encoder_def = ComponentDefinition(
        id=ResourceIdentity("e1"),
        category=ComponentCategory.FEEDBACK,
        model="mock.encoder",
        settings={"resolution": 1024},
    )
    encoder = registry.create(encoder_def)
    assert isinstance(encoder, MockEncoder)
    assert encoder.resolution_cpr == 1024

    camera_def = ComponentDefinition(
        id=ResourceIdentity("c1"),
        category=ComponentCategory.VISION,
        model="mock.camera",
        settings={"width": 160, "height": 120},
    )
    camera = registry.create(camera_def)
    assert isinstance(camera, MockCamera)
    assert camera.resolution == (160, 120)

    imu_def = ComponentDefinition(
        id=ResourceIdentity("i1"),
        category=ComponentCategory.SPATIAL,
        model="mock.imu",
        settings={"sample_rate_hz": 200},
    )
    imu = registry.create(imu_def)
    assert isinstance(imu, MockIMU)
    assert imu.sample_rate_hz == 200.0
