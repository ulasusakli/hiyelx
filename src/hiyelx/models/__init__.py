"""Explicit resource model registration and creation."""

from hiyelx.models.errors import (
    DuplicateModelRegistrationError,
    InvalidFactoryResultError,
    InvalidModelNameError,
    InvalidModelSettingsError,
    ModelCreationError,
    ModelRegistryError,
    UnknownModelError,
)
from hiyelx.models.registry import ModelRegistry, ResourceFactory

__all__ = [
    "DuplicateModelRegistrationError",
    "InvalidFactoryResultError",
    "InvalidModelNameError",
    "InvalidModelSettingsError",
    "ModelCreationError",
    "ModelRegistry",
    "ModelRegistryError",
    "ResourceFactory",
    "UnknownModelError",
]
