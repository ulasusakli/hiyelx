"""Typed exceptions for core component operations and registry."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from hiyelx.resources import ResourceIdentity


class CoreError(Exception):
    """Base exception for all core component errors."""


class DuplicateComponentRegistrationError(CoreError):
    """Raised when registering a component model name that is already registered."""

    def __init__(self, model_name: str) -> None:
        self.model_name = model_name
        super().__init__(f"duplicate component model registration {model_name!r}")


class UnknownComponentError(CoreError):
    """Raised when resolving an unregistered component model name."""

    def __init__(self, model_name: str) -> None:
        self.model_name = model_name
        super().__init__(f"unknown component model {model_name!r}")


class InvalidComponentModelNameError(CoreError):
    """Raised when registering a blank or invalid component model name."""

    def __init__(self, model_name: str) -> None:
        self.model_name = model_name
        super().__init__(f"invalid component model name {model_name!r}")


class ComponentCreationError(CoreError):
    """Raised when a component factory fails during instantiation."""

    def __init__(self, model_name: str, identity: ResourceIdentity) -> None:
        self.model_name = model_name
        self.identity = identity
        super().__init__(f"failed to create component {identity!s} using model {model_name!r}")


class InvalidComponentFactoryResultError(CoreError):
    """Raised when a factory returns an object that is not a Component."""

    def __init__(self, model_name: str, actual_type: type) -> None:
        self.model_name = model_name
        self.actual_type = actual_type
        super().__init__(
            f"factory for component model {model_name!r} returned "
            f"{actual_type.__name__}, expected Component"
        )
