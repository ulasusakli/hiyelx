"""Pydantic v2 schema and validator for Studio Application Workflows (applications/main.yaml)."""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path
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

from hiyelx.config.v2.models import RobotConfig
from hiyelx.project.errors import (
    ProjectLoadError,
    ProjectValidationError,
    UnsupportedProjectSchemaVersionError,
)

SUPPORTED_WORKFLOW_SCHEMA_VERSION: Final = "1"


class WorkflowFaultPolicy(StrEnum):
    """Explicit fault handling policy per workflow task (no silent auto-recovery)."""

    SAFE_STOP = "safe_stop"
    ABORT = "abort"
    DEGRADE = "degrade"


def _non_blank(value: str, label: str) -> str:
    if not value.strip():
        msg = f"{label} must not be blank"
        raise ValueError(msg)
    return value


def _parse_fault_policy(value: object) -> WorkflowFaultPolicy:
    if isinstance(value, WorkflowFaultPolicy):
        return value
    if isinstance(value, str):
        try:
            return WorkflowFaultPolicy(value)
        except ValueError as error:
            msg = f"unknown workflow fault policy {value!r}"
            raise ValueError(msg) from error
    msg = "on_fault must be a WorkflowFaultPolicy or string"
    raise ValueError(msg)


def _parse_string_tuple(value: object) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        msg = "next_tasks must be a list of task ids"
        raise ValueError(msg)
    items = cast(list[object] | tuple[object, ...], value)
    parsed: list[str] = []
    for item in items:
        if not isinstance(item, str) or not item.strip():
            msg = "task id entries must be non-blank strings"
            raise ValueError(msg)
        parsed.append(item)
    return tuple(parsed)


ConfiguredFaultPolicy = Annotated[WorkflowFaultPolicy, BeforeValidator(_parse_fault_policy)]
ConfiguredTaskRefs = Annotated[tuple[str, ...], BeforeValidator(_parse_string_tuple)]


class ApplicationMetadata(BaseModel):
    """Identity metadata for one robotics application workflow."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    id: str
    name: str
    version: str = "0.1.0"
    description: str | None = None

    @field_validator("id", "name", "version")
    @classmethod
    def _non_blank_meta(cls, value: str) -> str:
        return _non_blank(value, "application metadata field")


class WorkflowTask(BaseModel):
    """One declarative step executed by HIYELX Runtime (designed by Studio M07)."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    id: str
    name: str
    target_component: str
    action: str
    parameters: dict[str, object] = Field(default_factory=dict)
    timeout_ms: int = 3000
    on_fault: ConfiguredFaultPolicy = WorkflowFaultPolicy.SAFE_STOP
    next_tasks: ConfiguredTaskRefs = ()

    @field_validator("id", "name", "target_component", "action")
    @classmethod
    def _non_blank_fields(cls, value: str) -> str:
        return _non_blank(value, "workflow task field")

    @field_validator("timeout_ms")
    @classmethod
    def _positive_timeout(cls, value: int) -> int:
        if isinstance(value, bool) or value <= 0:
            msg = "timeout_ms must be a positive integer"
            raise ValueError(msg)
        return value


class ApplicationWorkflowDocument(BaseModel):
    """Declarative ``applications/main.yaml`` schema v1 document."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    schema_version: Literal["1"] = "1"
    application: ApplicationMetadata
    tasks: tuple[WorkflowTask, ...] = ()

    @model_validator(mode="after")
    def _validate_task_graph(self) -> Self:
        task_ids: set[str] = set()
        for task in self.tasks:
            if task.id in task_ids:
                msg = f"duplicate workflow task id {task.id!r}"
                raise ValueError(msg)
            task_ids.add(task.id)

        for task in self.tasks:
            for nxt in task.next_tasks:
                if nxt == task.id:
                    msg = f"workflow task {task.id!r} cannot transition directly to itself"
                    raise ValueError(msg)
                if nxt not in task_ids:
                    msg = f"workflow task {task.id!r} references unknown next task {nxt!r}"
                    raise ValueError(msg)
        return self


def load_workflow_from_str(
    source: str,
    *,
    path: Path = Path("applications/main.yaml"),
) -> ApplicationWorkflowDocument:
    """Parse and fail-closed validate one ``applications/main.yaml`` document."""
    try:
        raw = cast(object, yaml.safe_load(source))
    except yaml.YAMLError as error:
        raise ProjectLoadError(path, "workflow document could not be parsed as YAML") from error

    if not isinstance(raw, dict):
        raise ProjectValidationError(path, "workflow document root must be a mapping")

    mapping = cast(dict[str, object], raw)
    version = mapping.get("schema_version")
    if version != SUPPORTED_WORKFLOW_SCHEMA_VERSION:
        raise UnsupportedProjectSchemaVersionError(
            path,
            version if version is not None else "missing",
            SUPPORTED_WORKFLOW_SCHEMA_VERSION,
        )

    normalized: dict[str, object] = dict(mapping)
    tasks_raw = normalized.get("tasks")
    if isinstance(tasks_raw, list):
        normalized["tasks"] = tuple(cast(list[object], tasks_raw))

    try:
        return ApplicationWorkflowDocument.model_validate(normalized, strict=True)
    except ValidationError as error:
        raise ProjectValidationError(path, str(error)) from error


def validate_workflow_against_robot(
    workflow: ApplicationWorkflowDocument,
    robot_config: RobotConfig,
    *,
    path: Path = Path("applications/main.yaml"),
) -> None:
    """Verify every workflow task targets an existing component in ``RobotConfig``."""
    known_components = {component.id.value for component in robot_config.components}
    missing = [
        f"{task.id} -> {task.target_component}"
        for task in workflow.tasks
        if task.target_component not in known_components
    ]
    if missing:
        joined = ", ".join(missing)
        raise ProjectValidationError(
            path,
            f"workflow tasks reference unknown robot components: {joined}",
        )


def serialize_workflow_yaml(workflow: ApplicationWorkflowDocument) -> str:
    """Serialize a validated ApplicationWorkflowDocument into canonical YAML."""
    payload = workflow.model_dump(mode="json", exclude_none=True)
    return yaml.safe_dump(payload, sort_keys=False, allow_unicode=True)
