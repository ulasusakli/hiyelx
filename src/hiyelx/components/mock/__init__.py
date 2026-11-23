"""Canonical mock components for hardware-free simulation."""

from __future__ import annotations

from typing import TYPE_CHECKING

from hiyelx.components.mock.camera import MockCamera, create_mock_camera
from hiyelx.components.mock.encoder import MockEncoder, create_mock_encoder
from hiyelx.components.mock.imu import MockIMU, create_mock_imu
from hiyelx.components.mock.motor import MockMotor, create_mock_motor
from hiyelx.core.capabilities import ComponentCapability
from hiyelx.core.types import ComponentCategory

if TYPE_CHECKING:
    from hiyelx.core.registry import ComponentRegistry


def register_mock_components(registry: ComponentRegistry) -> None:
    """Register all 4 canonical mock component models in the provided registry."""
    # Actuator (Motor)
    motor_caps = (
        ComponentCapability.CAN_SET_VELOCITY,
        ComponentCapability.HAS_ANGULAR_POSITION,
        ComponentCapability.HAS_ANGULAR_VELOCITY,
    )
    registry.register("mock.motor", ComponentCategory.ACTUATOR, motor_caps, create_mock_motor)
    registry.register("motor.mock", ComponentCategory.ACTUATOR, motor_caps, create_mock_motor)

    # Feedback (Encoder)
    encoder_caps = (
        ComponentCapability.HAS_ENCODER_TICKS,
        ComponentCapability.HAS_ANGULAR_POSITION,
        ComponentCapability.HAS_ANGULAR_VELOCITY,
    )
    registry.register("mock.encoder", ComponentCategory.FEEDBACK, encoder_caps, create_mock_encoder)
    registry.register("encoder.mock", ComponentCategory.FEEDBACK, encoder_caps, create_mock_encoder)

    # Vision (Camera)
    camera_caps = (
        ComponentCapability.CAN_STREAM_FRAMES,
        ComponentCapability.HAS_RGB_FRAME,
    )
    registry.register("mock.camera", ComponentCategory.VISION, camera_caps, create_mock_camera)
    registry.register("camera.mock", ComponentCategory.VISION, camera_caps, create_mock_camera)

    # Spatial (IMU)
    imu_caps = (
        ComponentCapability.HAS_ORIENTATION_QUATERNION,
        ComponentCapability.HAS_ANGULAR_VELOCITY_3D,
        ComponentCapability.HAS_LINEAR_ACCELERATION_3D,
    )
    registry.register("mock.imu", ComponentCategory.SPATIAL, imu_caps, create_mock_imu)
    registry.register("imu.mock", ComponentCategory.SPATIAL, imu_caps, create_mock_imu)


__all__ = [
    "MockCamera",
    "MockEncoder",
    "MockIMU",
    "MockMotor",
    "create_mock_camera",
    "create_mock_encoder",
    "create_mock_imu",
    "create_mock_motor",
    "register_mock_components",
]
