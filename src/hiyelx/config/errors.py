"""Typed public errors for configuration loading and validation."""

from pathlib import Path


class ConfigurationError(Exception):
    """Base class for configuration errors."""


class ConfigurationLoadError(ConfigurationError):
    """Raised when a local configuration document cannot be loaded."""

    def __init__(self, path: Path, message: str) -> None:
        self.path = path
        super().__init__(f"cannot load configuration {path}: {message}")


class ConfigurationValidationError(ConfigurationError):
    """Raised when a parsed document does not satisfy the public schema."""

    def __init__(self, path: Path, message: str = "document validation failed") -> None:
        self.path = path
        super().__init__(f"invalid configuration {path}: {message}")


class UnsupportedSchemaVersionError(ConfigurationValidationError):
    """Raised when a document declares an unsupported schema version."""

    def __init__(self, path: Path, schema_version: object) -> None:
        self.schema_version = schema_version
        super().__init__(path, f"unsupported schema version {schema_version!r}")
