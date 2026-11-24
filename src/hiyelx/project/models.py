"""Pydantic v2 domain models for HIYELX Studio projects and general robot graphs."""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import StrEnum
from heapq import heappop, heappush
from pathlib import Path, PurePosixPath
from typing import Annotated, Final, Literal, Self

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, field_validator, model_validator

from hiyelx.config.v2.models import RobotConfig
from hiyelx.core.types import ComponentCategory
from hiyelx.project.errors import GraphDependencyCycleError

SUPPORTED_PROJECT_SCHEMA_VERSION: Final = "1"
SUPPORTED_GRAPH_SCHEMA_VERSION: Final = "1"
SUPPORTED_LAYOUT_SCHEMA_VERSION: Final = "1"


class StudioNodeKind(StrEnum):
    """Node taxonomy for the general Robot Builder graph (ADR 0002 v1.1)."""

    HARDWARE = "hardware"
    SENSOR = "sensor"
    ACTUATOR = "actuator"
    CONTROLLER = "controller"
    RUNTIME_COMPONENT = "runtime_component"
    COMMUNICATION = "communication"
    APPLICATION = "application"
    SAFETY = "safety"


class StudioEdgeKind(StrEnum):
    """Edge taxonomy separating general data/feedback flows from lifecycle DAG dependencies."""

    DATA = "data"
    COMMAND = "command"
    FEEDBACK = "feedback"
    DEPENDENCY = "dependency"
    PHYSICAL_CONNECTION = "physical_connection"


def _validate_non_blank(value: str, field_name: str) -> str:
    if not value.strip():
        msg = f"{field_name} must not be blank"
        raise ValueError(msg)
    return value


def _validate_relative_workspace_path(value: str) -> str:
    if not value.strip():
        msg = "workspace path must not be blank"
        raise ValueError(msg)
    if "\\" in value or value.startswith("/"):
        msg = f"workspace path {value!r} must be a relative POSIX path"
        raise ValueError(msg)
    pure = PurePosixPath(value)
    if pure.is_absolute() or any(part in {"", ".", ".."} for part in pure.parts):
        msg = f"workspace path {value!r} must not contain traversal segments"
        raise ValueError(msg)
    return value


class ProjectMetadata(BaseModel):
    """Identity metadata for one HIYELX Studio robot project."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    id: str
    name: str
    version: str = "0.1.0"
    description: str | None = None
    template: str | None = None

    @field_validator("id", "name", "version")
    @classmethod
    def _non_blank(cls, value: str) -> str:
        return _validate_non_blank(value, "project metadata field")


class WorkspacePaths(BaseModel):
    """Relative file paths inside a HIYELX Studio workspace."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    robot_config: str = "robot/robot.yaml"
    graph_file: str = "robot/connections/graph.yaml"
    layout_file: str = "robot/connections/layout.yaml"
    default_profile: str = "sim"

    @field_validator("robot_config", "graph_file", "layout_file")
    @classmethod
    def _valid_relative_path(cls, value: str) -> str:
        return _validate_relative_workspace_path(value)

    @field_validator("default_profile")
    @classmethod
    def _non_blank_profile(cls, value: str) -> str:
        return _validate_non_blank(value, "default_profile")


class ProfileDefinition(BaseModel):
    """One named environment profile (e.g. sim, dev, bench)."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    description: str
    overrides: str

    @field_validator("description")
    @classmethod
    def _non_blank_desc(cls, value: str) -> str:
        return _validate_non_blank(value, "description")

    @field_validator("overrides")
    @classmethod
    def _valid_overrides_path(cls, value: str) -> str:
        return _validate_relative_workspace_path(value)


class ProjectRuntimeContract(BaseModel):
    """Runtime compatibility contract declared by a Studio project."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    min_version: str = "0.2.0a1"
    robot_schema_version: Literal["2"] = "2"

    @field_validator("min_version")
    @classmethod
    def _non_blank_min_version(cls, value: str) -> str:
        return _validate_non_blank(value, "min_version")


class ProjectManifest(BaseModel):
    """Validated schema-v1 ``hiyelx.project.yaml`` document."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    schema_version: Literal["1"] = "1"
    project: ProjectMetadata
    workspace: WorkspacePaths = Field(default_factory=WorkspacePaths)
    profiles: dict[str, ProfileDefinition] = Field(default_factory=dict)
    runtime: ProjectRuntimeContract = Field(default_factory=ProjectRuntimeContract)

    @model_validator(mode="after")
    def _validate_default_profile(self) -> Self:
        if self.profiles and self.workspace.default_profile not in self.profiles:
            msg = (
                f"default_profile {self.workspace.default_profile!r} "
                "is not defined in profiles"
            )
            raise ValueError(msg)
        return self


def _parse_node_kind(value: object) -> StudioNodeKind:
    if isinstance(value, StudioNodeKind):
        return value
    if isinstance(value, str):
        try:
            return StudioNodeKind(value)
        except ValueError as error:
            msg = f"unknown studio node kind {value!r}"
            raise ValueError(msg) from error
    msg = "kind must be a StudioNodeKind or string"
    raise ValueError(msg)


def _parse_edge_kind(value: object) -> StudioEdgeKind:
    if isinstance(value, StudioEdgeKind):
        return value
    if isinstance(value, str):
        try:
            return StudioEdgeKind(value)
        except ValueError as error:
            msg = f"unknown studio edge kind {value!r}"
            raise ValueError(msg) from error
    msg = "kind must be a StudioEdgeKind or string"
    raise ValueError(msg)


def _parse_optional_category(value: object) -> ComponentCategory | None:
    if value is None or isinstance(value, ComponentCategory):
        return value
    if isinstance(value, str):
        try:
            return ComponentCategory(value)
        except ValueError as error:
            msg = f"unknown component category {value!r}"
            raise ValueError(msg) from error
    msg = "category must be a ComponentCategory, string, or None"
    raise ValueError(msg)


def _parse_finite_coordinate(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        msg = "canvas coordinate must be a finite number"
        raise ValueError(msg)
    result = float(value)
    if not math.isfinite(result):
        msg = "canvas coordinate must be finite"
        raise ValueError(msg)
    return result


ConfiguredNodeKind = Annotated[StudioNodeKind, BeforeValidator(_parse_node_kind)]
ConfiguredEdgeKind = Annotated[StudioEdgeKind, BeforeValidator(_parse_edge_kind)]
ConfiguredOptionalCategory = Annotated[
    ComponentCategory | None,
    BeforeValidator(_parse_optional_category),
]
ConfiguredCoordinate = Annotated[float, BeforeValidator(_parse_finite_coordinate)]


class GraphNode(BaseModel):
    """One node in the general Studio robot graph."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    id: str
    kind: ConfiguredNodeKind
    label: str
    component_id: str | None = None
    category: ConfiguredOptionalCategory = None
    model: str | None = None

    @field_validator("id", "label")
    @classmethod
    def _non_blank_identity(cls, value: str) -> str:
        return _validate_non_blank(value, "graph node field")

    @field_validator("component_id", "model")
    @classmethod
    def _optional_non_blank(cls, value: str | None) -> str | None:
        if value is not None:
            _validate_non_blank(value, "optional graph node field")
        return value


class GraphEdge(BaseModel):
    """One typed edge in the general Studio robot graph."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    id: str
    source: str
    target: str
    kind: ConfiguredEdgeKind
    source_port: str | None = None
    target_port: str | None = None
    topic: str | None = None

    @field_validator("id", "source", "target")
    @classmethod
    def _non_blank_edge_field(cls, value: str) -> str:
        return _validate_non_blank(value, "graph edge field")


class RobotGraphDocument(BaseModel):
    """General robot graph allowing feedback cycles while validating dependency DAGs."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    schema_version: Literal["1"] = "1"
    nodes: tuple[GraphNode, ...] = ()
    edges: tuple[GraphEdge, ...] = ()

    @model_validator(mode="after")
    def _validate_graph_references(self) -> Self:
        node_ids: set[str] = set()
        for node in self.nodes:
            if node.id in node_ids:
                msg = f"duplicate graph node id {node.id!r}"
                raise ValueError(msg)
            node_ids.add(node.id)

        edge_ids: set[str] = set()
        for edge in self.edges:
            if edge.id in edge_ids:
                msg = f"duplicate graph edge id {edge.id!r}"
                raise ValueError(msg)
            edge_ids.add(edge.id)
            if edge.source not in node_ids:
                msg = f"edge {edge.id!r} references unknown source node {edge.source!r}"
                raise ValueError(msg)
            if edge.target not in node_ids:
                msg = f"edge {edge.id!r} references unknown target node {edge.target!r}"
                raise ValueError(msg)
            if edge.kind is StudioEdgeKind.DEPENDENCY and edge.source == edge.target:
                msg = f"dependency edge {edge.id!r} cannot target itself ({edge.source!r})"
                raise ValueError(msg)
        return self

    def validate_dependency_dag(self, *, path: Path = Path("<graph>")) -> tuple[str, ...]:
        """Validate that ``dependency`` edges form a strict DAG and return startup order.

        Edge semantics: ``source`` is the prerequisite that must start before ``target``
        (i.e. ``target`` depends on ``source``). ``data``, ``command``, ``feedback``, and
        ``physical_connection`` edges are intentionally permitted to form cycles.
        """
        node_ids = tuple(sorted(node.id for node in self.nodes))
        prerequisites: dict[str, set[str]] = {node_id: set() for node_id in node_ids}
        dependents: dict[str, set[str]] = {node_id: set() for node_id in node_ids}

        for edge in self.edges:
            if edge.kind is not StudioEdgeKind.DEPENDENCY:
                continue
            prerequisites[edge.target].add(edge.source)
            dependents[edge.source].add(edge.target)

        indegree = {node_id: len(deps) for node_id, deps in prerequisites.items()}
        heap: list[str] = [node_id for node_id, count in indegree.items() if count == 0]
        heap.sort()
        order: list[str] = []

        while heap:
            current = heappop(heap)
            order.append(current)
            for dependent in sorted(dependents[current]):
                indegree[dependent] -= 1
                if indegree[dependent] == 0:
                    heappush(heap, dependent)

        if len(order) != len(node_ids):
            unresolved = frozenset(node_id for node_id, count in indegree.items() if count > 0)
            cycle = _find_directed_cycle(dependents, unresolved)
            raise GraphDependencyCycleError(path, cycle)

        return tuple(order)

    def project_depends_on(self) -> dict[str, tuple[str, ...]]:
        """Project ``dependency`` edges onto component-level ``depends_on`` tuples."""
        id_to_component = {
            node.id: node.component_id for node in self.nodes if node.component_id is not None
        }
        projected: dict[str, set[str]] = {
            comp_id: set() for comp_id in id_to_component.values()
        }
        for edge in self.edges:
            if edge.kind is not StudioEdgeKind.DEPENDENCY:
                continue
            source_comp = id_to_component.get(edge.source)
            target_comp = id_to_component.get(edge.target)
            if source_comp is not None and target_comp is not None:
                projected[target_comp].add(source_comp)
        return {comp_id: tuple(sorted(deps)) for comp_id, deps in sorted(projected.items())}


class NodePosition(BaseModel):
    """Visual 2D canvas coordinate stored separately from Runtime robot.yaml."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    x: ConfiguredCoordinate
    y: ConfiguredCoordinate


class CanvasLayoutDocument(BaseModel):
    """Visual layout metadata persisted in ``robot/connections/layout.yaml``."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    schema_version: Literal["1"] = "1"
    positions: dict[str, NodePosition] = Field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class LoadedStudioProject:
    """Fully validated Studio workspace separating project, robot config, graph, and layout."""

    root: Path
    manifest: ProjectManifest
    robot_config: RobotConfig
    graph: RobotGraphDocument
    layout: CanvasLayoutDocument


def _find_directed_cycle(
    adjacency: dict[str, set[str]],
    unresolved: frozenset[str],
) -> tuple[str, ...]:
    visited: set[str] = set()
    active_index: dict[str, int] = {}
    stack: list[str] = []

    def dfs(node_id: str) -> tuple[str, ...] | None:
        if node_id in active_index:
            start = active_index[node_id]
            return (*stack[start:], node_id)
        if node_id in visited:
            return None
        active_index[node_id] = len(stack)
        stack.append(node_id)
        for nxt in sorted(adjacency[node_id]):
            if nxt not in unresolved:
                continue
            found = dfs(nxt)
            if found is not None:
                return found
        stack.pop()
        active_index.pop(node_id)
        visited.add(node_id)
        return None

    for node_id in sorted(unresolved):
        found = dfs(node_id)
        if found is not None:
            return found

    raise AssertionError("unresolved dependency subgraph did not contain a cycle")
