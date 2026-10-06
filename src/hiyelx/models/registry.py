"""Instance-local, explicit registry for resource factories.

Configuration model names are resolved only against factories registered by
application composition code. The registry never imports configuration-sourced
Python paths, scans packages, or starts created resources.
"""

from collections.abc import Callable
from typing import cast

from hiyelx.config import ResourceDefinition
from hiyelx.models.errors import (
    DuplicateModelRegistrationError,
    InvalidFactoryResultError,
    InvalidModelNameError,
    ModelCreationError,
    UnknownModelError,
)
from hiyelx.resources import Resource

ResourceFactory = Callable[[ResourceDefinition], Resource]


class ModelRegistry:
    """An independent mapping of stable model names to resource factories."""

    def __init__(self) -> None:
        self._factories: dict[str, ResourceFactory] = {}

    def register(self, model_name: str, factory: ResourceFactory) -> None:
        """Explicitly register one factory under a stable model name."""
        self._validate_model_name(model_name)
        if model_name in self._factories:
            raise DuplicateModelRegistrationError(model_name)
        self._factories[model_name] = factory

    def resolve(self, model_name: str) -> ResourceFactory:
        """Resolve a registered factory without creating a resource."""
        self._validate_model_name(model_name)
        try:
            return self._factories[model_name]
        except KeyError as error:
            raise UnknownModelError(model_name) from error

    def create(self, definition: ResourceDefinition) -> Resource:
        """Create, but do not start, a resource from one validated definition."""
        factory = self.resolve(definition.model)
        try:
            factory_result = cast(object, factory(definition))
        except Exception as error:
            raise ModelCreationError(definition.model, definition.identity) from error
        if not isinstance(factory_result, Resource):
            raise InvalidFactoryResultError(definition.model, type(factory_result))
        return factory_result

    def registered_model_names(self) -> tuple[str, ...]:
        """Return registered model names in deterministic lexical order."""
        return tuple(sorted(self._factories))

    @staticmethod
    def _validate_model_name(model_name: str) -> None:
        if not model_name.strip():
            raise InvalidModelNameError(model_name)
