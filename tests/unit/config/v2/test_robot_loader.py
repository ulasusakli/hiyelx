from pathlib import Path

import pytest

from hiyelx.config.errors import (
    ConfigurationLoadError,
    ConfigurationValidationError,
    UnsupportedSchemaVersionError,
)
from hiyelx.config.v2 import load_robot_config, load_robot_config_from_str
from hiyelx.core.types import ComponentCategory
from hiyelx.resources import ResourceIdentity

VALID_ROBOT_YAML = """\
schema_version: "2"
robot:
  id: "scout-01"
  name: "Scout Rover"
  version: "1.0.0"
  description: "Autonomous inspection robot"
runtime:
  tick_rate_hz: 50.0
  log_level: "DEBUG"
components:
  - id: "front_encoder"
    category: "feedback"
    model: "encoder.mock"
    settings:
      resolution: 4096
  - id: "front_motor"
    category: "actuator"
    model: "motor.mock"
    driver: "driver.serial"
    depends_on:
      - "front_encoder"
    settings:
      max_rpm: 300
"""

VALID_ROBOT_JSON = """\
{
  "schema_version": "2",
  "robot": {
    "id": "scout-01",
    "name": "Scout Rover"
  },
  "components": [
    {
      "id": "camera_1",
      "category": "vision",
      "model": "camera.mock"
    }
  ]
}
"""


def test_load_valid_yaml(tmp_path: Path) -> None:
    config_file = tmp_path / "robot.yaml"
    config_file.write_text(VALID_ROBOT_YAML, encoding="utf-8")

    config = load_robot_config(config_file)
    assert config.schema_version == "2"
    assert config.robot.id == "scout-01"
    assert config.robot.name == "Scout Rover"
    assert config.runtime.tick_rate_hz == 50.0
    assert len(config.components) == 2
    assert config.components[0].id == ResourceIdentity("front_encoder")
    assert config.components[0].category == ComponentCategory.FEEDBACK
    assert config.components[1].depends_on == (ResourceIdentity("front_encoder"),)


def test_load_valid_json(tmp_path: Path) -> None:
    config_file = tmp_path / "robot.json"
    config_file.write_text(VALID_ROBOT_JSON, encoding="utf-8")

    config = load_robot_config(config_file)
    assert config.schema_version == "2"
    assert len(config.components) == 1
    assert config.components[0].category == ComponentCategory.VISION


def test_load_from_str() -> None:
    config = load_robot_config_from_str(VALID_ROBOT_YAML)
    assert config.robot.id == "scout-01"


def test_unsupported_schema_version_rejected(tmp_path: Path) -> None:
    config_file = tmp_path / "robot.yaml"
    config_file.write_text(VALID_ROBOT_YAML.replace('"2"', '"1"'), encoding="utf-8")

    with pytest.raises(UnsupportedSchemaVersionError) as caught:
        load_robot_config(config_file)

    assert caught.value.schema_version == "1"


def test_nonexistent_file_rejected(tmp_path: Path) -> None:
    missing_file = tmp_path / "does_not_exist.yaml"

    with pytest.raises(ConfigurationLoadError):
        load_robot_config(missing_file)


def test_unsupported_extension_rejected(tmp_path: Path) -> None:
    bad_ext_file = tmp_path / "robot.toml"
    bad_ext_file.write_text("data = 1", encoding="utf-8")

    with pytest.raises(ConfigurationLoadError, match="unsupported file extension"):
        load_robot_config(bad_ext_file)


def test_malformed_yaml_rejected(tmp_path: Path) -> None:
    bad_yaml = tmp_path / "robot.yaml"
    bad_yaml.write_text("components: [", encoding="utf-8")

    with pytest.raises(ConfigurationLoadError):
        load_robot_config(bad_yaml)


def test_validation_error_on_missing_required_fields(tmp_path: Path) -> None:
    bad_content = tmp_path / "robot.yaml"
    bad_content.write_text('schema_version: "2"\ncomponents: []', encoding="utf-8")

    with pytest.raises(ConfigurationValidationError):
        load_robot_config(bad_content)
