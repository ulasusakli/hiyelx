"""Safe local YAML and JSON configuration loader."""

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
from hiyelx.config.models import SUPPORTED_SCHEMA_VERSION, RuntimeConfig


def load_config(path: str | Path) -> RuntimeConfig:
    """Load and validate one local ``.yaml``, ``.yml``, or ``.json`` document."""
    config_path = Path(path)
    suffix = config_path.suffix.lower()
    if suffix not in {".yaml", ".yml", ".json"}:
        raise ConfigurationLoadError(config_path, f"unsupported file extension {suffix!r}")

    try:
        source = config_path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        raise ConfigurationLoadError(config_path, "file could not be read") from error

    try:
        if suffix == ".json":
            document = cast(object, json.loads(source))
        else:
            document = cast(object, yaml.safe_load(source))
    except (json.JSONDecodeError, yaml.YAMLError) as error:
        raise ConfigurationLoadError(config_path, "document could not be parsed") from error

    if not isinstance(document, dict):
        raise ConfigurationValidationError(config_path, "document root must be an object")

    raw_document = cast(dict[str, object], document)
    if (
        "schema_version" in raw_document
        and raw_document["schema_version"] != SUPPORTED_SCHEMA_VERSION
    ):
        raise UnsupportedSchemaVersionError(
            config_path,
            raw_document["schema_version"],
        )

    try:
        return RuntimeConfig.model_validate(raw_document, strict=True)
    except ValidationError as error:
        raise ConfigurationValidationError(config_path) from error
