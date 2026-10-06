from pathlib import Path

import pytest

from hiyelx.config import ResourceDefinition, RuntimeConfig, load_config
from hiyelx.models import ModelRegistry
from hiyelx.resources import Resource, ResourceIdentity
from hiyelx.runtime import (
    DependencyCycleError,
    DuplicateDependencyError,
    MissingDependencyError,
    RuntimeManager,
    SelfDependencyError,
)


def test_existing_config_without_dependencies_remains_valid(tmp_path: Path) -> None:
    config = load_config(
        _write(
            tmp_path / "runtime.yaml",
            """\
schema_version: "1"
resources:
  - identity: motor
    model: test.resource
    settings: {}
""",
        )
    )

    assert config.resources[0].depends_on == ()


@pytest.mark.parametrize(
    ("filename", "source"),
    [
        (
            "runtime.yaml",
            """\
schema_version: "1"
resources:
  - identity: controller
    model: test.resource
    settings: {}
    depends_on: [motor]
  - identity: motor
    model: test.resource
    settings: {}
    depends_on: []
""",
        ),
        (
            "runtime.json",
            """\
{"schema_version":"1","resources":[
  {"identity":"controller","model":"test.resource","settings":{},"depends_on":["motor"]},
  {"identity":"motor","model":"test.resource","settings":{},"depends_on":[]}
]}
""",
        ),
    ],
)
def test_valid_dependencies_parse_from_yaml_and_json(
    tmp_path: Path,
    filename: str,
    source: str,
) -> None:
    config = load_config(_write(tmp_path / filename, source))

    assert config.resources[0].depends_on == (ResourceIdentity("motor"),)
    assert config.resources[1].depends_on == ()


def test_duplicate_dependency_is_rejected_before_factory_invocation() -> None:
    creations, registry = _counting_registry()
    config = _config(_definition("controller", "motor", "motor"), _definition("motor"))

    with pytest.raises(DuplicateDependencyError) as caught:
        RuntimeManager(config, registry)

    assert caught.value.identity == ResourceIdentity("controller")
    assert caught.value.dependency == ResourceIdentity("motor")
    assert creations == []


def test_self_dependency_is_rejected_before_factory_invocation() -> None:
    creations, registry = _counting_registry()
    config = _config(_definition("controller", "controller"))

    with pytest.raises(SelfDependencyError):
        RuntimeManager(config, registry)

    assert creations == []


def test_missing_dependency_is_rejected_before_factory_invocation() -> None:
    creations, registry = _counting_registry()
    config = _config(_definition("controller", "missing"))

    with pytest.raises(MissingDependencyError) as caught:
        RuntimeManager(config, registry)

    assert caught.value.dependency == ResourceIdentity("missing")
    assert creations == []


def test_direct_dependency_cycle_is_rejected() -> None:
    config = _config(_definition("a", "b"), _definition("b", "a"))

    with pytest.raises(DependencyCycleError) as caught:
        RuntimeManager(config, ModelRegistry())

    assert caught.value.identities == (ResourceIdentity("a"), ResourceIdentity("b"))


def test_multi_resource_dependency_cycle_is_rejected() -> None:
    config = _config(
        _definition("a", "c"),
        _definition("b", "a"),
        _definition("c", "b"),
        _definition("downstream", "a"),
    )

    with pytest.raises(DependencyCycleError) as caught:
        RuntimeManager(config, ModelRegistry())

    assert caught.value.identities == (
        ResourceIdentity("a"),
        ResourceIdentity("b"),
        ResourceIdentity("c"),
    )


def test_valid_dag_uses_lexically_smallest_topological_plan() -> None:
    config = _config(
        _definition("sensor"),
        _definition("controller", "motor", "sensor"),
        _definition("motor"),
    )

    manager = RuntimeManager(config, _registry())

    assert manager.startup_plan == (
        ResourceIdentity("motor"),
        ResourceIdentity("sensor"),
        ResourceIdentity("controller"),
    )


def test_independent_resources_are_ordered_lexically() -> None:
    config = _config(_definition("z"), _definition("a"), _definition("m"))

    manager = RuntimeManager(config, _registry())

    assert manager.startup_plan == tuple(map(ResourceIdentity, ("a", "m", "z")))


def test_input_document_order_does_not_change_plan() -> None:
    definitions = (
        _definition("controller", "motor"),
        _definition("sensor"),
        _definition("motor"),
    )

    first = RuntimeManager(_config(*definitions), _registry())
    second = RuntimeManager(_config(*reversed(definitions)), _registry())

    assert first.startup_plan == second.startup_plan


def test_every_dependency_precedes_its_dependent() -> None:
    config = _config(
        _definition("application", "controller", "sensor"),
        _definition("controller", "motor"),
        _definition("sensor"),
        _definition("motor"),
    )
    manager = RuntimeManager(config, _registry())
    positions = {identity: index for index, identity in enumerate(manager.startup_plan)}

    for definition in config.resources:
        for dependency in definition.depends_on:
            assert positions[dependency] < positions[definition.identity]


def _definition(identity: str, *depends_on: str) -> ResourceDefinition:
    return ResourceDefinition(
        identity=ResourceIdentity(identity),
        model="test.resource",
        settings={},
        depends_on=tuple(map(ResourceIdentity, depends_on)),
    )


def _config(*definitions: ResourceDefinition) -> RuntimeConfig:
    return RuntimeConfig(schema_version="1", resources=list(definitions))


def _registry() -> ModelRegistry:
    registry = ModelRegistry()
    registry.register("test.resource", lambda definition: Resource(definition.identity))
    return registry


def _counting_registry() -> tuple[list[ResourceIdentity], ModelRegistry]:
    creations: list[ResourceIdentity] = []

    def factory(definition: ResourceDefinition) -> Resource:
        creations.append(definition.identity)
        return Resource(definition.identity)

    registry = ModelRegistry()
    registry.register("test.resource", factory)
    return creations, registry


def _write(path: Path, source: str) -> Path:
    path.write_text(source, encoding="utf-8")
    return path
