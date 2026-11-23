"""Configuration loader for robot.yaml schema version 2."""

from __future__ import annotations

import json
from pathlib import Path
from typing import cast

import yaml
from pydantic import ValidationError

from hiyelx.config.errors import (
    ConfigurationLoadError,
    ConfigurationValidationError,
    UnsupportedSchemaVersionError,
)
from hiyelx.config.v2.models import SUPPORTED_ROBOT_SCHEMA_VERSION, RobotConfig


def load_robot_config(path: str | Path) -> RobotConfig:
    """Load and validate one local ``robot.yaml``, ``.yml``, or ``.json`` document."""
    config_path = Path(path)
    suffix = config_path.suffix.lower()
    if suffix not in {".yaml", ".yml", ".json"}:
        raise ConfigurationLoadError(config_path, f"unsupported file extension {suffix!r}")

    try:
        source = config_path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        raise ConfigurationLoadError(config_path, "file could not be read") from error

    return load_robot_config_from_str(source, path=config_path)


def load_robot_config_from_str(source: str, path: Path | None = None) -> RobotConfig:
    """Parse and validate configuration content from string."""
    config_path = path or Path("<string>")

    try:
        document = cast(object, yaml.safe_load(source))
    except (json.JSONDecodeError, yaml.YAMLError) as error:
        raise ConfigurationLoadError(config_path, "document could not be parsed") from error

    if not isinstance(document, dict):
        raise ConfigurationValidationError(config_path, "document root must be an object")

    raw_document = cast(dict[str, object], document)
    version = raw_document.get("schema_version")
    if version != SUPPORTED_ROBOT_SCHEMA_VERSION:
        raise UnsupportedSchemaVersionError(
            config_path,
            version if version is not None else "missing",
        )

    try:
        return RobotConfig.model_validate(raw_document, strict=True)
    except ValidationError as error:
        raise ConfigurationValidationError(config_path) from error
