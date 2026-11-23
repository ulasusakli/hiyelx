"""Vendor-neutral component contracts and canonical mock fleet."""

from hiyelx.components.mock import (
    MockCamera,
    MockEncoder,
    MockIMU,
    MockMotor,
    create_mock_camera,
    create_mock_encoder,
    create_mock_imu,
    create_mock_motor,
    register_mock_components,
)
from hiyelx.components.motor import (
    InvalidMotorCommandError,
    InvalidMotorStateError,
    Motor,
    MotorCommand,
    MotorError,
    MotorState,
    MotorUnavailableError,
)

__all__ = [
    "InvalidMotorCommandError",
    "InvalidMotorStateError",
    "MockCamera",
    "MockEncoder",
    "MockIMU",
    "MockMotor",
    "Motor",
    "MotorCommand",
    "MotorError",
    "MotorState",
    "MotorUnavailableError",
    "create_mock_camera",
    "create_mock_encoder",
    "create_mock_imu",
    "create_mock_motor",
    "register_mock_components",
]
