import pytest
from pydantic import ValidationError

from hiyelx.config.v2.models import (
    ComponentDefinition,
    RobotConfig,
    RobotMetadata,
    RuntimeSettings,
)
from hiyelx.core.types import ComponentCategory
from hiyelx.resources import ResourceIdentity


def test_valid_robot_config() -> None:
    config = RobotConfig(
        schema_version="2",
        robot=RobotMetadata(id="robot-01", name="Mobile Base"),
        components=[
            ComponentDefinition(
                id=ResourceIdentity("encoder_1"),
                category=ComponentCategory.FEEDBACK,
                model="mock.encoder",
            ),
            ComponentDefinition(
                id=ResourceIdentity("motor_1"),
                category=ComponentCategory.ACTUATOR,
                model="mock.motor",
                depends_on=(ResourceIdentity("encoder_1"),),
            ),
        ],
    )

    assert config.schema_version == "2"
    assert config.robot.id == "robot-01"
    assert config.robot.name == "Mobile Base"
    assert config.runtime.tick_rate_hz == 100.0
    assert len(config.components) == 2
    assert config.components[1].depends_on == (ResourceIdentity("encoder_1"),)


@pytest.mark.parametrize("blank_value", ["", "   "])
def test_robot_metadata_blank_id_or_name_rejected(blank_value: str) -> None:
    with pytest.raises(ValidationError):
        RobotMetadata(id=blank_value, name="Robot")

    with pytest.raises(ValidationError):
        RobotMetadata(id="robot-01", name=blank_value)


def test_runtime_settings_non_positive_tick_rate_rejected() -> None:
    with pytest.raises(ValidationError):
        RuntimeSettings(tick_rate_hz=0.0)

    with pytest.raises(ValidationError):
        RuntimeSettings(tick_rate_hz=-10.0)


def test_duplicate_component_identities_rejected() -> None:
    with pytest.raises(ValidationError, match="duplicate component identity"):
        RobotConfig(
            robot=RobotMetadata(id="r1", name="R1"),
            components=[
                ComponentDefinition(
                    id=ResourceIdentity("motor_1"),
                    category=ComponentCategory.ACTUATOR,
                    model="mock.motor",
                ),
                ComponentDefinition(
                    id=ResourceIdentity("motor_1"),
                    category=ComponentCategory.ACTUATOR,
                    model="mock.motor",
                ),
            ],
        )


def test_self_dependency_rejected() -> None:
    with pytest.raises(ValidationError, match="cannot depend on itself"):
        RobotConfig(
            robot=RobotMetadata(id="r1", name="R1"),
            components=[
                ComponentDefinition(
                    id=ResourceIdentity("motor_1"),
                    category=ComponentCategory.ACTUATOR,
                    model="mock.motor",
                    depends_on=(ResourceIdentity("motor_1"),),
                ),
            ],
        )


def test_unknown_dependency_rejected() -> None:
    with pytest.raises(ValidationError, match="depends on unknown component"):
        RobotConfig(
            robot=RobotMetadata(id="r1", name="R1"),
            components=[
                ComponentDefinition(
                    id=ResourceIdentity("motor_1"),
                    category=ComponentCategory.ACTUATOR,
                    model="mock.motor",
                    depends_on=(ResourceIdentity("non_existent"),),
                ),
            ],
        )


def test_unknown_field_rejected() -> None:
    with pytest.raises(ValidationError):
        RobotConfig(
            robot=RobotMetadata(id="r1", name="R1"),
            components=[],
            unexpected_field="disallowed",  # type: ignore
        )
