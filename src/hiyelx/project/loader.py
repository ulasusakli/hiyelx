"""Fail-closed loader, path confinement, and atomic persistence for Studio projects."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path, PurePosixPath
from typing import cast

import yaml
from pydantic import ValidationError

from hiyelx.config.errors import ConfigurationError
from hiyelx.config.v2.loader import load_robot_config
from hiyelx.config.v2.models import RobotConfig
from hiyelx.project.errors import (
    ProjectLoadError,
    ProjectPathError,
    ProjectValidationError,
    UnsupportedProjectSchemaVersionError,
)
from hiyelx.project.models import (
    SUPPORTED_GRAPH_SCHEMA_VERSION,
    SUPPORTED_LAYOUT_SCHEMA_VERSION,
    SUPPORTED_PROJECT_SCHEMA_VERSION,
    CanvasLayoutDocument,
    LoadedStudioProject,
    ProjectManifest,
    RobotGraphDocument,
)
from hiyelx.runtime.errors import RuntimeTopologyError
from hiyelx.runtime.planning import plan_startup

PROJECT_MANIFEST_FILENAME = "hiyelx.project.yaml"


def resolve_workspace_path(root: Path, relative_path: str) -> Path:
    """Resolve one relative path strictly inside ``root`` without symlink escape."""
    if not relative_path.strip():
        raise ProjectPathError(relative_path, "path must not be blank")
    if "\\" in relative_path or relative_path.startswith("/"):
        raise ProjectPathError(relative_path, "path must be relative POSIX")
    pure = PurePosixPath(relative_path)
    if pure.is_absolute() or any(part in {"", ".", ".."} for part in pure.parts):
        raise ProjectPathError(relative_path, "path contains forbidden traversal segments")

    resolved_root = root.resolve()
    current = resolved_root
    for part in pure.parts:
        current = current / part
        if current.is_symlink():
            raise ProjectPathError(relative_path, f"symlink component {part!r} is forbidden")

    resolved_target = current.resolve()
    try:
        resolved_target.relative_to(resolved_root)
    except ValueError as error:
        raise ProjectPathError(relative_path, "path escapes workspace root") from error
    return resolved_target


def atomic_write_text(root: Path, relative_path: str, content: str) -> Path:
    """Atomically write UTF-8 text inside ``root`` using temp file + fsync + replace."""
    target = resolve_workspace_path(root, relative_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    # Re-verify parent containment after directory creation.
    resolve_workspace_path(root, relative_path)

    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=target.parent,
            prefix=f".{target.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temp_path = Path(handle.name)
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, target)
        temp_path = None
        return target
    finally:
        if temp_path is not None and temp_path.exists():
            temp_path.unlink(missing_ok=True)


def _read_yaml_mapping(path: Path, expected_schema_version: str) -> dict[str, object]:
    try:
        source = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        raise ProjectLoadError(path, "file could not be read") from error

    try:
        loaded = cast(object, yaml.safe_load(source))
    except yaml.YAMLError as error:
        raise ProjectLoadError(path, "document could not be parsed as YAML") from error

    if not isinstance(loaded, dict):
        raise ProjectValidationError(path, "document root must be a mapping")

    mapping = cast(dict[str, object], loaded)
    version = mapping.get("schema_version")
    if version != expected_schema_version:
        raise UnsupportedProjectSchemaVersionError(
            path,
            version if version is not None else "missing",
            expected_schema_version,
        )
    return mapping


def load_project_manifest(path: Path) -> ProjectManifest:
    """Load and validate ``hiyelx.project.yaml`` (schema v1)."""
    mapping = _read_yaml_mapping(path, SUPPORTED_PROJECT_SCHEMA_VERSION)
    try:
        return ProjectManifest.model_validate(mapping, strict=True)
    except ValidationError as error:
        raise ProjectValidationError(path, str(error)) from error


def load_robot_graph(path: Path) -> RobotGraphDocument:
    """Load and validate ``graph.yaml`` including strict dependency DAG verification."""
    mapping = _read_yaml_mapping(path, SUPPORTED_GRAPH_SCHEMA_VERSION)
    # Normalize YAML list entries into tuples for strict Pydantic validation.
    normalized: dict[str, object] = dict(mapping)
    for key in ("nodes", "edges"):
        raw = normalized.get(key)
        if isinstance(raw, list):
            normalized[key] = tuple(cast(list[object], raw))
    try:
        graph = RobotGraphDocument.model_validate(normalized, strict=True)
    except ValidationError as error:
        raise ProjectValidationError(path, str(error)) from error
    graph.validate_dependency_dag(path=path)
    return graph


def load_canvas_layout(path: Path) -> CanvasLayoutDocument:
    """Load and validate ``layout.yaml`` (schema v1)."""
    mapping = _read_yaml_mapping(path, SUPPORTED_LAYOUT_SCHEMA_VERSION)
    try:
        return CanvasLayoutDocument.model_validate(mapping, strict=True)
    except ValidationError as error:
        raise ProjectValidationError(path, str(error)) from error


def load_studio_project(root: str | Path) -> LoadedStudioProject:
    """Load and cross-validate a complete HIYELX Studio workspace from disk."""
    workspace_root = Path(root)
    if not workspace_root.is_dir():
        raise ProjectLoadError(workspace_root, "workspace root directory does not exist")

    manifest_path = resolve_workspace_path(workspace_root, PROJECT_MANIFEST_FILENAME)
    manifest = load_project_manifest(manifest_path)

    robot_path = resolve_workspace_path(workspace_root, manifest.workspace.robot_config)
    try:
        robot_config = load_robot_config(robot_path)
    except ConfigurationError as error:
        raise ProjectValidationError(robot_path, str(error)) from error

    try:
        plan_startup(robot_config)
    except RuntimeTopologyError as error:
        raise ProjectValidationError(robot_path, str(error)) from error

    graph_path = resolve_workspace_path(workspace_root, manifest.workspace.graph_file)
    graph = load_robot_graph(graph_path)

    layout_path = resolve_workspace_path(workspace_root, manifest.workspace.layout_file)
    layout = load_canvas_layout(layout_path)

    component_ids = {component.id.value for component in robot_config.components}
    for node in graph.nodes:
        if node.component_id is not None and node.component_id not in component_ids:
            raise ProjectValidationError(
                graph_path,
                f"graph node {node.id!r} references unknown robot component "
                f"{node.component_id!r}",
            )

    return LoadedStudioProject(
        root=workspace_root.resolve(),
        manifest=manifest,
        robot_config=robot_config,
        graph=graph,
        layout=layout,
    )


def serialize_project_manifest_yaml(manifest: ProjectManifest) -> str:
    """Serialize a validated ProjectManifest into canonical YAML."""
    payload = manifest.model_dump(mode="json", exclude_none=True)
    return yaml.safe_dump(payload, sort_keys=False, allow_unicode=True)


def serialize_robot_config_yaml(config: RobotConfig) -> str:
    """Serialize a validated RobotConfig v2 into canonical YAML."""
    payload: dict[str, object] = {
        "schema_version": config.schema_version,
        "robot": config.robot.model_dump(mode="json", exclude_none=True),
        "runtime": config.runtime.model_dump(mode="json"),
        "components": [
            {
                "id": comp.id.value,
                "category": str(comp.category),
                "model": comp.model,
                **({"driver": comp.driver} if comp.driver is not None else {}),
                **(
                    {"depends_on": [dep.value for dep in comp.depends_on]}
                    if comp.depends_on
                    else {}
                ),
                "settings": dict(comp.settings),
            }
            for comp in config.components
        ],
    }
    return yaml.safe_dump(payload, sort_keys=False, allow_unicode=True)
