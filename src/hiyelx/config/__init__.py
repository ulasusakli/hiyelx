"""Versioned local configuration loading and validation.

Schema version ``"1"`` defines a document with a ``resources`` list.
Schema version ``"2"`` defines a robot system document (``robot.yaml``) with
metadata, runtime settings, and typed components.
"""

from hiyelx.config.errors import (
    ConfigurationError,
    ConfigurationLoadError,
    ConfigurationValidationError,
    UnsupportedSchemaVersionError,
)
from hiyelx.config.loader import load_config
from hiyelx.config.models import (
    SUPPORTED_SCHEMA_VERSION,
    ResourceDefinition,
    RuntimeConfig,
)
from hiyelx.config.v2 import (
    SUPPORTED_ROBOT_SCHEMA_VERSION,
    ComponentDefinition,
    RobotConfig,
    RobotMetadata,
    RuntimeSettings,
    load_robot_config,
    load_robot_config_from_str,
)

__all__ = [
    "SUPPORTED_ROBOT_SCHEMA_VERSION",
    "SUPPORTED_SCHEMA_VERSION",
    "ComponentDefinition",
    "ConfigurationError",
    "ConfigurationLoadError",
    "ConfigurationValidationError",
    "ResourceDefinition",
    "RobotConfig",
    "RobotMetadata",
    "RuntimeConfig",
    "RuntimeSettings",
    "UnsupportedSchemaVersionError",
    "load_config",
    "load_robot_config",
    "load_robot_config_from_str",
]
