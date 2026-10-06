"""Pydantic models for HIYELX configuration schema version 1."""

from __future__ import annotations

from typing import Annotated, Final, Literal, Self, cast

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    field_validator,
    model_validator,
)

from hiyelx.resources import ResourceIdentity

SUPPORTED_SCHEMA_VERSION: Final = "1"


def _resource_identity(value: object) -> ResourceIdentity:
    if isinstance(value, ResourceIdentity):
        return value
    if not isinstance(value, str):
        msg = "resource identity must be a string"
        raise ValueError(msg)
    return ResourceIdentity(value)


ConfiguredResourceIdentity = Annotated[
    ResourceIdentity,
    BeforeValidator(_resource_identity),
]


def _resource_dependencies(value: object) -> tuple[ResourceIdentity, ...]:
    if not isinstance(value, (list, tuple)):
        msg = "depends_on must be a list of resource identities"
        raise ValueError(msg)
    dependencies = cast(list[object] | tuple[object, ...], value)
    return tuple(_resource_identity(dependency) for dependency in dependencies)


ConfiguredResourceDependencies = Annotated[
    tuple[ResourceIdentity, ...],
    BeforeValidator(_resource_dependencies),
]


class ResourceDefinition(BaseModel):
    """One resource identity, registry model name, and model settings."""

    model_config = ConfigDict(
        arbitrary_types_allowed=True,
        extra="forbid",
        frozen=True,
        strict=True,
    )

    identity: ConfiguredResourceIdentity
    model: str
    settings: dict[str, object]
    depends_on: ConfiguredResourceDependencies = ()

    @field_validator("model")
    @classmethod
    def _model_must_not_be_empty(cls, value: str) -> str:
        if not value.strip():
            msg = "model name must not be empty"
            raise ValueError(msg)
        return value


class RuntimeConfig(BaseModel):
    """Validated HIYELX runtime configuration schema version 1."""

    model_config = ConfigDict(
        arbitrary_types_allowed=True,
        extra="forbid",
        frozen=True,
        strict=True,
    )

    schema_version: Literal["1"]
    resources: list[ResourceDefinition]

    @model_validator(mode="after")
    def _resource_identities_must_be_unique(self) -> Self:
        identities: set[ResourceIdentity] = set()
        for resource in self.resources:
            if resource.identity in identities:
                msg = f"duplicate resource identity {resource.identity!s}"
                raise ValueError(msg)
            identities.add(resource.identity)
        return self
