"""Pydantic v2 schema for hiyelx.manifest.yaml (manifest_version: 1.0)."""

from __future__ import annotations

import re
from enum import StrEnum
from pathlib import Path, PurePosixPath
from typing import Annotated, Final, Literal, Self, cast

import yaml
from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)

from hiyelx.core.capabilities import ComponentCapability
from hiyelx.core.types import ComponentCategory
from hiyelx.manifests.errors import (
    ManifestLoadError,
    ManifestValidationError,
    UnsupportedManifestVersionError,
)

SUPPORTED_MANIFEST_VERSION: Final = "1.0"

_VERSION_RE = re.compile(
    r"^(?P<major>0|[1-9]\d*)\.(?P<minor>0|[1-9]\d*)\.(?P<patch>0|[1-9]\d*)"
    r"(?:(?P<pre_tag>a|b|rc)(?P<pre_num>\d+))?$"
)


class ManifestType(StrEnum):
    """Classification of one installable or built-in HIYELX unit."""

    DRIVER = "driver"
    COMPONENT = "component"
    SERVICE = "service"


class InterfaceDirection(StrEnum):
    """Signal/message direction on one declared manifest interface."""

    INPUT = "input"
    OUTPUT = "output"
    BIDIRECTIONAL = "bidirectional"


def _non_blank(value: str, label: str) -> str:
    if not value.strip():
        msg = f"{label} must not be blank"
        raise ValueError(msg)
    return value


def _validate_version_string(value: str) -> str:
    if _VERSION_RE.fullmatch(value) is None:
        msg = f"invalid version {value!r}; expected MAJOR.MINOR.PATCH[a|b|rcN]"
        raise ValueError(msg)
    return value


def _validate_relative_schema_path(value: str) -> str:
    if not value.strip() or "\\" in value or value.startswith("/"):
        msg = f"configuration schema path {value!r} must be a relative POSIX path"
        raise ValueError(msg)
    pure = PurePosixPath(value)
    if pure.is_absolute() or any(part in {"", ".", ".."} for part in pure.parts):
        msg = f"configuration schema path {value!r} must not contain traversal segments"
        raise ValueError(msg)
    return value


def _parse_manifest_type(value: object) -> ManifestType:
    if isinstance(value, ManifestType):
        return value
    if isinstance(value, str):
        try:
            return ManifestType(value)
        except ValueError as error:
            msg = f"unknown manifest type {value!r}"
            raise ValueError(msg) from error
    msg = "type must be a ManifestType or string"
    raise ValueError(msg)


def _parse_category(value: object) -> ComponentCategory:
    if isinstance(value, ComponentCategory):
        return value
    if isinstance(value, str):
        try:
            return ComponentCategory(value)
        except ValueError as error:
            msg = f"unknown component category {value!r}"
            raise ValueError(msg) from error
    msg = "category must be a ComponentCategory or string"
    raise ValueError(msg)


def _parse_direction(value: object) -> InterfaceDirection:
    if isinstance(value, InterfaceDirection):
        return value
    if isinstance(value, str):
        try:
            return InterfaceDirection(value)
        except ValueError as error:
            msg = f"unknown interface direction {value!r}"
            raise ValueError(msg) from error
    msg = "direction must be an InterfaceDirection or string"
    raise ValueError(msg)


def _parse_capabilities(value: object) -> tuple[ComponentCapability, ...]:
    if not isinstance(value, (list, tuple)):
        msg = "capabilities must be a list of ComponentCapability identifiers"
        raise ValueError(msg)
    raw_items = cast(list[object] | tuple[object, ...], value)
    parsed: list[ComponentCapability] = []
    for item in raw_items:
        if isinstance(item, ComponentCapability):
            parsed.append(item)
        elif isinstance(item, str):
            try:
                parsed.append(ComponentCapability(item))
            except ValueError as error:
                msg = f"unknown capability {item!r}"
                raise ValueError(msg) from error
        else:
            msg = "capability entries must be strings or ComponentCapability"
            raise ValueError(msg)
    return tuple(parsed)


ConfiguredManifestType = Annotated[ManifestType, BeforeValidator(_parse_manifest_type)]
ConfiguredCategory = Annotated[ComponentCategory, BeforeValidator(_parse_category)]
ConfiguredDirection = Annotated[InterfaceDirection, BeforeValidator(_parse_direction)]
ConfiguredCapabilities = Annotated[
    tuple[ComponentCapability, ...],
    BeforeValidator(_parse_capabilities),
]


class ManifestRuntimeRequirement(BaseModel):
    """Runtime version compatibility bounds declared by a component or driver."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    min_version: str
    max_version: str | None = None

    @field_validator("min_version")
    @classmethod
    def _valid_min(cls, value: str) -> str:
        return _validate_version_string(value)

    @field_validator("max_version")
    @classmethod
    def _valid_max(cls, value: str | None) -> str | None:
        if value is not None:
            _validate_version_string(value)
        return value


class ManifestInterface(BaseModel):
    """One typed input/output/bidirectional interface declared by a manifest."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    name: str
    type: str
    direction: ConfiguredDirection = InterfaceDirection.BIDIRECTIONAL

    @field_validator("name", "type")
    @classmethod
    def _non_blank_fields(cls, value: str) -> str:
        return _non_blank(value, "interface field")


class ManifestDependency(BaseModel):
    """One declared dependency on another component/driver manifest."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    id: str
    min_version: str | None = None

    @field_validator("id")
    @classmethod
    def _non_blank_id(cls, value: str) -> str:
        return _non_blank(value, "dependency id")

    @field_validator("min_version")
    @classmethod
    def _valid_dep_min(cls, value: str | None) -> str | None:
        if value is not None:
            _validate_version_string(value)
        return value


class ManifestConfigurationSpec(BaseModel):
    """Configuration schema reference and optional default settings."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    schema_path: str = Field(alias="schema")
    defaults: dict[str, object] = Field(default_factory=dict)

    @field_validator("schema_path")
    @classmethod
    def _valid_schema_path(cls, value: str) -> str:
        return _validate_relative_schema_path(value)


class ComponentManifest(BaseModel):
    """Canonical ``hiyelx.manifest.yaml`` v1.0 contract (ADR 0002 v1.1 Decision 9)."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True, populate_by_name=True)

    manifest_version: Literal["1.0"] = "1.0"
    id: str
    model: str
    name: str
    version: str
    type: ConfiguredManifestType
    category: ConfiguredCategory
    description: str | None = None
    runtime: ManifestRuntimeRequirement
    capabilities: ConfiguredCapabilities = ()
    interfaces: tuple[ManifestInterface, ...] = ()
    dependencies: tuple[ManifestDependency, ...] = ()
    configuration: ManifestConfigurationSpec
    scaffold_command: str | None = None

    @field_validator("id", "model", "name")
    @classmethod
    def _non_blank_identity(cls, value: str) -> str:
        return _non_blank(value, "manifest field")

    @field_validator("version")
    @classmethod
    def _valid_version(cls, value: str) -> str:
        return _validate_version_string(value)

    @model_validator(mode="after")
    def _validate_uniqueness(self) -> Self:
        if len(set(self.capabilities)) != len(self.capabilities):
            msg = f"manifest {self.id!r} contains duplicate capabilities"
            raise ValueError(msg)
        interface_names = [iface.name for iface in self.interfaces]
        if len(set(interface_names)) != len(interface_names):
            msg = f"manifest {self.id!r} contains duplicate interface names"
            raise ValueError(msg)
        dep_ids = [dep.id for dep in self.dependencies]
        if len(set(dep_ids)) != len(dep_ids):
            msg = f"manifest {self.id!r} contains duplicate dependencies"
            raise ValueError(msg)
        if self.id in dep_ids:
            msg = f"manifest {self.id!r} cannot depend on itself"
            raise ValueError(msg)
        return self


def load_manifest_from_str(source: str, *, path: Path = Path("<manifest>")) -> ComponentManifest:
    """Parse and fail-closed validate one ``hiyelx.manifest.yaml`` string."""
    try:
        raw = cast(object, yaml.safe_load(source))
    except yaml.YAMLError as error:
        raise ManifestLoadError(path, "document could not be parsed as YAML") from error

    if not isinstance(raw, dict):
        raise ManifestValidationError(path, "manifest root must be a YAML mapping")

    mapping = cast(dict[str, object], raw)
    version = mapping.get("manifest_version")
    if version != SUPPORTED_MANIFEST_VERSION:
        raise UnsupportedManifestVersionError(
            path,
            version if version is not None else "missing",
            SUPPORTED_MANIFEST_VERSION,
        )

    normalized: dict[str, object] = dict(mapping)
    for key in ("interfaces", "dependencies"):
        entry = normalized.get(key)
        if isinstance(entry, list):
            normalized[key] = tuple(cast(list[object], entry))

    try:
        return ComponentManifest.model_validate(normalized, strict=True)
    except ValidationError as error:
        raise ManifestValidationError(path, str(error)) from error


def load_manifest_file(path: str | Path) -> ComponentManifest:
    """Load and validate one ``hiyelx.manifest.yaml`` file from disk."""
    manifest_path = Path(path)
    try:
        source = manifest_path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        raise ManifestLoadError(manifest_path, "file could not be read") from error
    return load_manifest_from_str(source, path=manifest_path)
