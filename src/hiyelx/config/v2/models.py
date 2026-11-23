"""Pydantic models for HIYELX Robot configuration schema version 2."""

from __future__ import annotations

from typing import Annotated, Final, Literal, Self, cast

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

from hiyelx.core.types import ComponentCategory
from hiyelx.resources import ResourceIdentity

SUPPORTED_ROBOT_SCHEMA_VERSION: Final = "2"


def _resource_identity(value: object) -> ResourceIdentity:
    if isinstance(value, ResourceIdentity):
        return value
    if not isinstance(value, str):
        msg = "component identity must be a string"
        raise ValueError(msg)
    return ResourceIdentity(value)


ConfiguredComponentIdentity = Annotated[
    ResourceIdentity,
    BeforeValidator(_resource_identity),
]


def _resource_dependencies(value: object) -> tuple[ResourceIdentity, ...]:
    if not isinstance(value, (list, tuple)):
        msg = "depends_on must be a list of component identities"
        raise ValueError(msg)
    dependencies = cast(list[object] | tuple[object, ...], value)
    return tuple(_resource_identity(dep) for dep in dependencies)


ConfiguredComponentDependencies = Annotated[
    tuple[ResourceIdentity, ...],
    BeforeValidator(_resource_dependencies),
]


class RobotMetadata(BaseModel):
    """Immutable metadata identifying the robotic system."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        strict=True,
    )

    id: str
    name: str
    version: str = "0.1.0"
    description: str | None = None

    @field_validator("id", "name")
    @classmethod
    def _must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            msg = "field must not be blank"
            raise ValueError(msg)
        return value


class RuntimeSettings(BaseModel):
    """Local runtime execution parameters."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        strict=True,
    )

    tick_rate_hz: float = 100.0
    log_level: str = "INFO"
    history_retention_days: int = 7

    @field_validator("tick_rate_hz")
    @classmethod
    def _tick_rate_must_be_positive(cls, value: float) -> float:
        if value <= 0.0:
            msg = "tick_rate_hz must be positive"
            raise ValueError(msg)
        return value


def _component_category(value: object) -> ComponentCategory:
    if isinstance(value, ComponentCategory):
        return value
    if isinstance(value, str):
        try:
            return ComponentCategory(value.lower().strip())
        except ValueError as error:
            msg = f"unknown component category {value!r}"
            raise ValueError(msg) from error
    msg = "category must be a string or ComponentCategory"
    raise ValueError(msg)


ConfiguredComponentCategory = Annotated[
    ComponentCategory,
    BeforeValidator(_component_category),
]


class ComponentDefinition(BaseModel):
    """Configuration definition for one robotic component."""

    model_config = ConfigDict(
        arbitrary_types_allowed=True,
        extra="forbid",
        frozen=True,
        strict=True,
    )

    id: ConfiguredComponentIdentity
    category: ConfiguredComponentCategory
    model: str
    driver: str | None = None
    settings: dict[str, object] = Field(default_factory=dict)
    depends_on: ConfiguredComponentDependencies = ()

    @field_validator("model")
    @classmethod
    def _model_must_not_be_empty(cls, value: str) -> str:
        if not value.strip():
            msg = "model name must not be empty"
            raise ValueError(msg)
        return value


class RobotConfig(BaseModel):
    """Validated HIYELX Robot configuration schema version 2."""

    model_config = ConfigDict(
        arbitrary_types_allowed=True,
        extra="forbid",
        frozen=True,
        strict=True,
    )

    schema_version: Literal["2"] = "2"
    robot: RobotMetadata
    runtime: RuntimeSettings = Field(default_factory=RuntimeSettings)
    components: list[ComponentDefinition]

    @model_validator(mode="after")
    def _validate_components(self) -> Self:
        identities: set[ResourceIdentity] = set()
        for comp in self.components:
            if comp.id in identities:
                msg = f"duplicate component identity {comp.id!s}"
                raise ValueError(msg)
            identities.add(comp.id)

        for comp in self.components:
            if comp.id in comp.depends_on:
                msg = f"component {comp.id!s} cannot depend on itself"
                raise ValueError(msg)
            for dep in comp.depends_on:
                if dep not in identities:
                    msg = f"component {comp.id!s} depends on unknown component {dep!s}"
                    raise ValueError(msg)

        return self
