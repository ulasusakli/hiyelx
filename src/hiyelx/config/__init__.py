"""Versioned local configuration loading and validation.

Schema version ``"1"`` defines a document with a ``resources`` list. Each
resource has a string ``identity``, a non-empty registry ``model`` name, and an
object-valued ``settings`` mapping. Loading validates data only; it never
creates or starts resources.
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

__all__ = [
    "SUPPORTED_SCHEMA_VERSION",
    "ConfigurationError",
    "ConfigurationLoadError",
    "ConfigurationValidationError",
    "ResourceDefinition",
    "RuntimeConfig",
    "UnsupportedSchemaVersionError",
    "load_config",
]
