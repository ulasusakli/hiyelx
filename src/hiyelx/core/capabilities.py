"""Core component capability taxonomy."""

from __future__ import annotations

from enum import StrEnum


class ComponentCapability(StrEnum):
    """Fine-grained behavioral capabilities declared by components."""

    # Actuator capabilities
    CAN_SET_VELOCITY = "can_set_velocity"
    CAN_SET_POSITION = "can_set_position"
    CAN_SET_TORQUE = "can_set_torque"

    # Vision capabilities
    CAN_STREAM_FRAMES = "can_stream_frames"
    HAS_RGB_FRAME = "has_rgb_frame"
    HAS_DEPTH_FRAME = "has_depth_frame"

    # Spatial / IMU capabilities
    HAS_ORIENTATION_QUATERNION = "has_orientation_quaternion"
    HAS_ANGULAR_VELOCITY_3D = "has_angular_velocity_3d"
    HAS_LINEAR_ACCELERATION_3D = "has_linear_acceleration_3d"

    # Feedback / Encoder capabilities
    HAS_ENCODER_TICKS = "has_encoder_ticks"
    HAS_ANGULAR_POSITION = "has_angular_position"
    HAS_ANGULAR_VELOCITY = "has_angular_velocity"

    def __str__(self) -> str:
        return self.value
