"""Typed public errors for model registration and resource creation."""

from hiyelx.resources import ResourceIdentity


class ModelRegistryError(Exception):
    """Base class for model registry errors."""


class InvalidModelNameError(ModelRegistryError):
    """Raised when an empty model name is registered or resolved."""

    def __init__(self, model_name: str) -> None:
        self.model_name = model_name
        super().__init__("model name must not be empty")


class DuplicateModelRegistrationError(ModelRegistryError):
    """Raised when a model name is already registered in this registry."""

    def __init__(self, model_name: str) -> None:
        self.model_name = model_name
        super().__init__(f"model {model_name!r} is already registered")


class UnknownModelError(ModelRegistryError):
    """Raised when a model name is not registered in this registry."""

    def __init__(self, model_name: str) -> None:
        self.model_name = model_name
        super().__init__(f"model {model_name!r} is not registered")


class ModelCreationError(ModelRegistryError):
    """Raised when a registered factory fails to create a resource."""

    def __init__(self, model_name: str, identity: ResourceIdentity) -> None:
        self.model_name = model_name
        self.identity = identity
        super().__init__(f"model {model_name!r} failed to create resource {identity!s}")


class InvalidFactoryResultError(ModelRegistryError):
    """Raised when a registered factory does not return a Resource."""

    def __init__(self, model_name: str, result_type: type[object]) -> None:
        self.model_name = model_name
        self.result_type = result_type
        super().__init__(
            f"model {model_name!r} factory returned {result_type.__name__}, not Resource"
        )


class InvalidModelSettingsError(ModelRegistryError):
    """Raised when model-specific settings fail validation."""

    def __init__(self, model_name: str) -> None:
        self.model_name = model_name
        super().__init__(f"invalid settings for model {model_name!r}")
