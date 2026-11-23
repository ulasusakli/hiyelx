"""Instance-local, explicit registry for component factories and capabilities."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from hiyelx.config.v2.models import ComponentDefinition
from hiyelx.core.capabilities import ComponentCapability
from hiyelx.core.component import Component
from hiyelx.core.errors import (
    ComponentCreationError,
    DuplicateComponentRegistrationError,
    InvalidComponentFactoryResultError,
    InvalidComponentModelNameError,
    UnknownComponentError,
)
from hiyelx.core.types import ComponentCategory

ComponentFactory = Callable[[Any], Component]


@dataclass(frozen=True, slots=True)
class RegisteredComponent:
    """Metadata and factory registration for one component model."""

    model_name: str
    category: ComponentCategory
    capabilities: frozenset[ComponentCapability]
    factory: ComponentFactory


class ComponentRegistry:
    """Independent mapping of stable model names to component factories and traits."""

    def __init__(self) -> None:
        self._registry: dict[str, RegisteredComponent] = {}

    def register(
        self,
        model_name: str,
        category: ComponentCategory,
        capabilities: Iterable[ComponentCapability],
        factory: ComponentFactory,
    ) -> None:
        """Register one component model with explicit category, capabilities, and factory."""
        self._validate_model_name(model_name)
        if model_name in self._registry:
            raise DuplicateComponentRegistrationError(model_name)

        self._registry[model_name] = RegisteredComponent(
            model_name=model_name,
            category=category,
            capabilities=frozenset(capabilities),
            factory=factory,
        )

    def resolve(self, model_name: str) -> RegisteredComponent:
        """Resolve a registered component entry without instantiating it."""
        self._validate_model_name(model_name)
        try:
            return self._registry[model_name]
        except KeyError as error:
            raise UnknownComponentError(model_name) from error

    def create(self, definition: ComponentDefinition) -> Component:
        """Create, but do not start, a component from a validated definition."""
        registered = self.resolve(definition.model)
        try:
            result = cast(object, registered.factory(definition))
        except Exception as error:
            raise ComponentCreationError(definition.model, definition.id) from error

        if not isinstance(result, Component):
            raise InvalidComponentFactoryResultError(definition.model, type(result))

        return result

    def registered_models(self) -> tuple[str, ...]:
        """Return all registered model names in sorted order."""
        return tuple(sorted(self._registry))

    def by_category(self, category: ComponentCategory) -> tuple[str, ...]:
        """Return model names matching the specified category in sorted order."""
        return tuple(
            sorted(
                model_name
                for model_name, info in self._registry.items()
                if info.category is category
            )
        )

    def by_capability(self, capability: ComponentCapability) -> tuple[str, ...]:
        """Return model names declaring the specified capability in sorted order."""
        return tuple(
            sorted(
                model_name
                for model_name, info in self._registry.items()
                if capability in info.capabilities
            )
        )

    @staticmethod
    def _validate_model_name(model_name: str) -> None:
        if not model_name.strip():
            raise InvalidComponentModelNameError(model_name)
