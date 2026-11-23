import pytest

from hiyelx.config.v2.models import ComponentDefinition
from hiyelx.core import (
    Component,
    ComponentCapability,
    ComponentCategory,
    ComponentCreationError,
    ComponentRegistry,
    DuplicateComponentRegistrationError,
    InvalidComponentFactoryResultError,
    InvalidComponentModelNameError,
    UnknownComponentError,
)
from hiyelx.resources import ResourceIdentity


class DummyComponent(Component):
    def __init__(self, identity: ResourceIdentity, category: ComponentCategory) -> None:
        super().__init__(identity, category=category)


def test_register_and_resolve() -> None:
    registry = ComponentRegistry()

    def factory(definition: ComponentDefinition) -> Component:
        return DummyComponent(definition.id, ComponentCategory.VISION)

    registry.register(
        "camera.mock",
        ComponentCategory.VISION,
        (ComponentCapability.CAN_STREAM_FRAMES, ComponentCapability.HAS_RGB_FRAME),
        factory,
    )

    info = registry.resolve("camera.mock")
    assert info.model_name == "camera.mock"
    assert info.category == ComponentCategory.VISION
    assert ComponentCapability.CAN_STREAM_FRAMES in info.capabilities
    assert info.factory is factory


def _dummy_actuator(d: ComponentDefinition) -> Component:
    return DummyComponent(d.id, ComponentCategory.ACTUATOR)


def _dummy_spatial(d: ComponentDefinition) -> Component:
    return DummyComponent(d.id, ComponentCategory.SPATIAL)


def test_duplicate_registration_rejected() -> None:
    registry = ComponentRegistry()
    registry.register("test.model", ComponentCategory.ACTUATOR, (), _dummy_actuator)

    with pytest.raises(DuplicateComponentRegistrationError):
        registry.register("test.model", ComponentCategory.ACTUATOR, (), _dummy_actuator)


@pytest.mark.parametrize("invalid_name", ["", "   "])
def test_invalid_model_name_rejected(invalid_name: str) -> None:
    registry = ComponentRegistry()
    with pytest.raises(InvalidComponentModelNameError):
        registry.register(invalid_name, ComponentCategory.ACTUATOR, (), _dummy_actuator)


def test_unknown_model_resolve_rejected() -> None:
    registry = ComponentRegistry()
    with pytest.raises(UnknownComponentError):
        registry.resolve("non_existent")


def test_create_successful() -> None:
    registry = ComponentRegistry()
    registry.register("sensor.test", ComponentCategory.SPATIAL, (), _dummy_spatial)

    definition = ComponentDefinition(
        id=ResourceIdentity("imu_1"),
        category=ComponentCategory.SPATIAL,
        model="sensor.test",
    )

    component = registry.create(definition)
    assert isinstance(component, DummyComponent)
    assert component.identity == ResourceIdentity("imu_1")
    assert component.category == ComponentCategory.SPATIAL


def test_create_invalid_factory_result_rejected() -> None:
    registry = ComponentRegistry()
    registry.register("sensor.bad", ComponentCategory.SPATIAL, (), lambda d: "not_a_component")  # type: ignore

    definition = ComponentDefinition(
        id=ResourceIdentity("bad_1"),
        category=ComponentCategory.SPATIAL,
        model="sensor.bad",
    )

    with pytest.raises(InvalidComponentFactoryResultError):
        registry.create(definition)


def test_create_factory_exception_wrapped() -> None:
    def failing_factory(d: ComponentDefinition) -> Component:
        msg = "boom"
        raise RuntimeError(msg)

    registry = ComponentRegistry()
    registry.register("sensor.exploding", ComponentCategory.SPATIAL, (), failing_factory)

    definition = ComponentDefinition(
        id=ResourceIdentity("boom_1"),
        category=ComponentCategory.SPATIAL,
        model="sensor.exploding",
    )

    with pytest.raises(ComponentCreationError) as caught:
        registry.create(definition)

    assert isinstance(caught.value.__cause__, RuntimeError)


def test_queries_by_category_and_capability() -> None:
    registry = ComponentRegistry()
    registry.register(
        "motor.mock",
        ComponentCategory.ACTUATOR,
        (ComponentCapability.CAN_SET_VELOCITY,),
        lambda d: DummyComponent(d.id, ComponentCategory.ACTUATOR),
    )
    registry.register(
        "camera.mock",
        ComponentCategory.VISION,
        (ComponentCapability.CAN_STREAM_FRAMES,),
        lambda d: DummyComponent(d.id, ComponentCategory.VISION),
    )
    registry.register(
        "imu.mock",
        ComponentCategory.SPATIAL,
        (ComponentCapability.HAS_ORIENTATION_QUATERNION,),
        lambda d: DummyComponent(d.id, ComponentCategory.SPATIAL),
    )

    assert registry.registered_models() == ("camera.mock", "imu.mock", "motor.mock")
    assert registry.by_category(ComponentCategory.ACTUATOR) == ("motor.mock",)
    assert registry.by_category(ComponentCategory.VISION) == ("camera.mock",)
    assert registry.by_capability(ComponentCapability.CAN_STREAM_FRAMES) == ("camera.mock",)
    assert registry.by_capability(ComponentCapability.HAS_ENCODER_TICKS) == ()
