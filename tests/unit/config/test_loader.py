from pathlib import Path

import pytest

from hiyelx.config import (
    ConfigurationLoadError,
    ConfigurationValidationError,
    ResourceDefinition,
    RuntimeConfig,
    UnsupportedSchemaVersionError,
    load_config,
)
from hiyelx.models import ModelRegistry
from hiyelx.resources import Resource, ResourceIdentity

VALID_YAML = """\
schema_version: "1"
resources:
  - identity: left_motor
    model: motor.simulated
    settings: {}
"""

VALID_JSON = """\
{
  "schema_version": "1",
  "resources": [
    {"identity": "left_motor", "model": "motor.simulated", "settings": {}}
  ]
}
"""


def test_valid_yaml_loading(tmp_path: Path) -> None:
    config = load_config(_write(tmp_path / "runtime.yaml", VALID_YAML))

    assert config.schema_version == "1"
    assert config.resources[0].identity == ResourceIdentity("left_motor")
    assert config.resources[0].model == "motor.simulated"
    assert config.resources[0].settings == {}


def test_valid_yml_loading(tmp_path: Path) -> None:
    config = load_config(_write(tmp_path / "runtime.yml", VALID_YAML))

    assert config.resources[0].identity == ResourceIdentity("left_motor")


def test_valid_json_loading(tmp_path: Path) -> None:
    config = load_config(_write(tmp_path / "runtime.json", VALID_JSON))

    assert isinstance(config, RuntimeConfig)
    assert config.resources[0].model == "motor.simulated"


def test_yaml_and_json_produce_equivalent_configuration(tmp_path: Path) -> None:
    yaml_config = load_config(_write(tmp_path / "runtime.yaml", VALID_YAML))
    json_config = load_config(_write(tmp_path / "runtime.json", VALID_JSON))

    assert yaml_config == json_config


@pytest.mark.parametrize(
    ("filename", "source"),
    [
        ("runtime.yaml", "resources: ["),
        ("runtime.json", '{"schema_version": "1",'),
    ],
)
def test_malformed_documents_preserve_parser_error_as_cause(
    tmp_path: Path,
    filename: str,
    source: str,
) -> None:
    with pytest.raises(ConfigurationLoadError) as caught:
        load_config(_write(tmp_path / filename, source))

    assert caught.value.__cause__ is not None


def test_yaml_uses_safe_loading(tmp_path: Path) -> None:
    source = '!!python/object/apply:builtins.str ["unsafe"]'

    with pytest.raises(ConfigurationLoadError):
        load_config(_write(tmp_path / "runtime.yaml", source))


def test_unsupported_schema_version(tmp_path: Path) -> None:
    source = VALID_JSON.replace('"schema_version": "1"', '"schema_version": "2"')

    with pytest.raises(UnsupportedSchemaVersionError) as caught:
        load_config(_write(tmp_path / "runtime.json", source))

    assert caught.value.schema_version == "2"


@pytest.mark.parametrize(
    "source",
    [
        '{"resources": []}',
        '{"schema_version": "1"}',
        '{"schema_version": "1", "resources": [{"model": "x", "settings": {}}]}',
        '{"schema_version": "1", "resources": [{"identity": "x", "settings": {}}]}',
        '{"schema_version": "1", "resources": [{"identity": "x", "model": "x"}]}',
    ],
)
def test_missing_required_fields_are_rejected(tmp_path: Path, source: str) -> None:
    with pytest.raises(ConfigurationValidationError):
        load_config(_write(tmp_path / "runtime.json", source))


@pytest.mark.parametrize(
    "source",
    [
        '{"schema_version": "1", "resources": [], "unknown": true}',
        (
            '{"schema_version": "1", "resources": '
            '[{"identity": "x", "model": "x", "settings": {}, "unknown": true}]}'
        ),
    ],
)
def test_unknown_fields_are_rejected(tmp_path: Path, source: str) -> None:
    with pytest.raises(ConfigurationValidationError):
        load_config(_write(tmp_path / "runtime.json", source))


@pytest.mark.parametrize("model_name", ["", "   "])
def test_empty_model_name_is_rejected(tmp_path: Path, model_name: str) -> None:
    source = (
        '{"schema_version": "1", "resources": '
        f'[{{"identity": "x", "model": {model_name!r}, "settings": {{}}}}]}}'
    ).replace("'", '"')

    with pytest.raises(ConfigurationValidationError):
        load_config(_write(tmp_path / "runtime.json", source))


def test_duplicate_resource_identity_is_rejected(tmp_path: Path) -> None:
    source = """\
schema_version: "1"
resources:
  - identity: duplicate
    model: first
    settings: {}
  - identity: duplicate
    model: second
    settings: {}
"""

    with pytest.raises(ConfigurationValidationError):
        load_config(_write(tmp_path / "runtime.yaml", source))


@pytest.mark.parametrize("source", ["null", "[]", '"string"', "1"])
def test_non_object_document_root_is_rejected(tmp_path: Path, source: str) -> None:
    with pytest.raises(ConfigurationValidationError):
        load_config(_write(tmp_path / "runtime.json", source))


@pytest.mark.parametrize(
    "source",
    [
        '{"schema_version": "1", "resources": {}}',
        (
            '{"schema_version": "1", "resources": '
            '[{"identity": {"value": "x"}, "model": "x", "settings": {}}]}'
        ),
        (
            '{"schema_version": "1", "resources": '
            '[{"identity": "x", "model": "x", "settings": []}]}'
        ),
    ],
)
def test_structurally_invalid_values_are_not_coerced(tmp_path: Path, source: str) -> None:
    with pytest.raises(ConfigurationValidationError):
        load_config(_write(tmp_path / "runtime.json", source))


def test_loading_does_not_invoke_registered_factories(tmp_path: Path) -> None:
    creations = 0

    def factory(definition: ResourceDefinition) -> Resource:
        nonlocal creations
        creations += 1
        return Resource(definition.identity)

    registry = ModelRegistry()
    registry.register("motor.simulated", factory)

    config = load_config(_write(tmp_path / "runtime.yaml", VALID_YAML))

    assert config.resources
    assert creations == 0


def _write(path: Path, source: str) -> Path:
    path.write_text(source, encoding="utf-8")
    return path
