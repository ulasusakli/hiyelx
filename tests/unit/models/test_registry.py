from typing import cast

import pytest

from hiyelx.config import ResourceDefinition
from hiyelx.models import (
    DuplicateModelRegistrationError,
    InvalidFactoryResultError,
    InvalidModelNameError,
    ModelCreationError,
    ModelRegistry,
    UnknownModelError,
)
from hiyelx.resources import LifecycleState, Resource, ResourceIdentity


def test_successful_registration_and_resolution() -> None:
    registry = ModelRegistry()
    registry.register("resource.basic", _resource_factory)

    assert registry.resolve("resource.basic") is _resource_factory


def test_registered_model_names_are_deterministically_sorted() -> None:
    registry = ModelRegistry()
    registry.register("z.model", _resource_factory)
    registry.register("a.model", _resource_factory)
    registry.register("m.model", _resource_factory)

    assert registry.registered_model_names() == ("a.model", "m.model", "z.model")


def test_duplicate_registration_is_rejected() -> None:
    registry = ModelRegistry()
    registry.register("resource.basic", _resource_factory)

    with pytest.raises(DuplicateModelRegistrationError):
        registry.register("resource.basic", _resource_factory)


@pytest.mark.parametrize("model_name", ["", "  "])
def test_empty_registration_name_is_rejected(model_name: str) -> None:
    with pytest.raises(InvalidModelNameError):
        ModelRegistry().register(model_name, _resource_factory)


def test_unknown_model_is_rejected() -> None:
    registry = ModelRegistry()

    with pytest.raises(UnknownModelError) as caught:
        registry.resolve("missing.model")

    assert isinstance(caught.value.__cause__, KeyError)


def test_factory_creates_resource_without_starting_it() -> None:
    registry = ModelRegistry()
    registry.register("resource.basic", _resource_factory)

    resource = registry.create(_definition())

    assert resource.identity == ResourceIdentity("resource/one")
    assert resource.state is LifecycleState.CREATED


def test_factory_exception_is_preserved_as_cause() -> None:
    failure = RuntimeError("factory failed")

    def failing_factory(definition: ResourceDefinition) -> Resource:
        raise failure

    registry = ModelRegistry()
    registry.register("resource.basic", failing_factory)

    with pytest.raises(ModelCreationError) as caught:
        registry.create(_definition())

    assert caught.value.__cause__ is failure


def test_invalid_factory_return_is_rejected() -> None:
    def invalid_factory(definition: ResourceDefinition) -> Resource:
        return cast(Resource, object())

    registry = ModelRegistry()
    registry.register("resource.basic", invalid_factory)

    with pytest.raises(InvalidFactoryResultError) as caught:
        registry.create(_definition())

    assert caught.value.result_type is object


def test_registry_instances_do_not_share_state() -> None:
    first = ModelRegistry()
    second = ModelRegistry()
    first.register("resource.basic", _resource_factory)

    assert first.registered_model_names() == ("resource.basic",)
    assert second.registered_model_names() == ()
    with pytest.raises(UnknownModelError):
        second.resolve("resource.basic")


def _definition() -> ResourceDefinition:
    return ResourceDefinition(
        identity=ResourceIdentity("resource/one"),
        model="resource.basic",
        settings={},
    )


def _resource_factory(definition: ResourceDefinition) -> Resource:
    return Resource(definition.identity)
