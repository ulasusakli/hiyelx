"""Public helpers for building explicit HIYELX modules and drivers."""

from hiyelx.sdk.errors import (
    DriverSdkError,
    InvalidMotorDriverResultError,
    InvalidScaffoldModelNameError,
    InvalidScaffoldPackageNameError,
    MotorDriverScaffoldError,
    ScaffoldParentMissingError,
    ScaffoldTargetExistsError,
)
from hiyelx.sdk.motor_driver import MotorDriverBuilder, register_motor_driver
from hiyelx.sdk.scaffold import create_motor_driver_scaffold

__all__ = [
    "DriverSdkError",
    "InvalidMotorDriverResultError",
    "InvalidScaffoldModelNameError",
    "InvalidScaffoldPackageNameError",
    "MotorDriverBuilder",
    "MotorDriverScaffoldError",
    "ScaffoldParentMissingError",
    "ScaffoldTargetExistsError",
    "create_motor_driver_scaffold",
    "register_motor_driver",
]
