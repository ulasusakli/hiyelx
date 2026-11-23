"""HIYELX Core Component & Capabilities contracts."""

from hiyelx.core.capabilities import ComponentCapability
from hiyelx.core.component import Component
from hiyelx.core.errors import (
    ComponentCreationError,
    CoreError,
    DuplicateComponentRegistrationError,
    InvalidComponentFactoryResultError,
    InvalidComponentModelNameError,
    UnknownComponentError,
)
from hiyelx.core.registry import (
    ComponentFactory,
    ComponentRegistry,
    RegisteredComponent,
)
from hiyelx.core.types import ComponentCategory

__all__ = [
    "Component",
    "ComponentCapability",
    "ComponentCategory",
    "ComponentCreationError",
    "ComponentFactory",
    "ComponentRegistry",
    "CoreError",
    "DuplicateComponentRegistrationError",
    "InvalidComponentFactoryResultError",
    "InvalidComponentModelNameError",
    "RegisteredComponent",
    "UnknownComponentError",
]
