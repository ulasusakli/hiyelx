from pathlib import Path

import pytest
import yaml

from hiyelx.config.v2.loader import load_robot_config
from hiyelx.project import (
    PROJECT_MANIFEST_FILENAME,
    STARTER_TEMPLATES,
    GraphDependencyCycleError,
    GraphEdge,
    GraphNode,
    ProjectPathError,
    ProjectTemplateError,
    ProjectValidationError,
    RobotGraphDocument,
    StudioEdgeKind,
    StudioNodeKind,
    UnsupportedProjectSchemaVersionError,
    atomic_write_text,
    create_studio_project,
    load_studio_project,
    resolve_workspace_path,
)
from hiyelx.runtime.planning import plan_startup


@pytest.mark.parametrize("template", STARTER_TEMPLATES)
def test_starter_templates_create_valid_projects_and_runtime_v2_configs(
    tmp_path: Path,
    template: str,
) -> None:
    target = tmp_path / f"proj-{template}"
    loaded = create_studio_project(
        target,
        project_id=f"robot-{template}",
        project_name=f"Robot {template}",
        template=template,
    )

    assert loaded.root == target.resolve()
    assert loaded.manifest.schema_version == "1"
    assert loaded.manifest.project.template == template
    assert (target / PROJECT_MANIFEST_FILENAME).is_file()
    assert (target / "robot/robot.yaml").is_file()
    assert (target / "robot/connections/graph.yaml").is_file()
    assert (target / "robot/connections/layout.yaml").is_file()

    # Robot config must validate directly through Runtime v2 loader and planner.
    reloaded_robot = load_robot_config(target / "robot/robot.yaml")
    assert reloaded_robot == loaded.robot_config
    plan_startup(reloaded_robot)

    # Full workspace reload round-trip.
    reloaded_project = load_studio_project(target)
    assert reloaded_project == loaded


def test_canonical_mock_rover_supports_feedback_cycle_and_acyclic_dependencies(
    tmp_path: Path,
) -> None:
    loaded = create_studio_project(
        tmp_path / "rover",
        project_id="rover-01",
        project_name="Rover 01",
        template="canonical-mock-rover",
    )

    edge_kinds = {edge.kind for edge in loaded.graph.edges}
    assert StudioEdgeKind.FEEDBACK in edge_kinds
    assert StudioEdgeKind.COMMAND in edge_kinds
    assert StudioEdgeKind.DATA in edge_kinds
    assert StudioEdgeKind.DEPENDENCY in edge_kinds

    startup_order = loaded.graph.validate_dependency_dag()
    assert startup_order.index("wheel_encoder") < startup_order.index("drive_motor")
    assert startup_order.index("drive_motor") < startup_order.index("base_imu")
    assert startup_order.index("base_imu") < startup_order.index("front_camera")

    assert loaded.graph.project_depends_on() == {
        "base_imu": ("drive_motor",),
        "drive_motor": ("wheel_encoder",),
        "front_camera": ("base_imu",),
        "wheel_encoder": (),
    }


def test_dependency_cycle_is_rejected_while_feedback_cycle_is_allowed() -> None:
    nodes = (
        GraphNode(id="a", kind=StudioNodeKind.SENSOR, label="A"),
        GraphNode(id="b", kind=StudioNodeKind.CONTROLLER, label="B"),
        GraphNode(id="c", kind=StudioNodeKind.ACTUATOR, label="C"),
    )
    feedback_graph = RobotGraphDocument(
        schema_version="1",
        nodes=nodes,
        edges=(
            GraphEdge(id="e1", source="a", target="b", kind=StudioEdgeKind.DATA),
            GraphEdge(id="e2", source="b", target="c", kind=StudioEdgeKind.COMMAND),
            GraphEdge(id="e3", source="c", target="b", kind=StudioEdgeKind.FEEDBACK),
        ),
    )
    assert feedback_graph.validate_dependency_dag() == ("a", "b", "c")

    cyclic_deps = RobotGraphDocument(
        schema_version="1",
        nodes=nodes,
        edges=(
            GraphEdge(id="d1", source="a", target="b", kind=StudioEdgeKind.DEPENDENCY),
            GraphEdge(id="d2", source="b", target="c", kind=StudioEdgeKind.DEPENDENCY),
            GraphEdge(id="d3", source="c", target="a", kind=StudioEdgeKind.DEPENDENCY),
        ),
    )
    with pytest.raises(GraphDependencyCycleError) as caught:
        cyclic_deps.validate_dependency_dag()
    assert caught.value.cycle == ("a", "b", "c", "a")


def test_workspace_path_confinement_blocks_traversal_absolute_and_symlinks(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "secret.yaml"
    outside.write_text("secret: true\n", encoding="utf-8")

    for bad in ("", "  ", "/etc/passwd", "../secret.yaml", "robot/../../secret.yaml", "a\\b.yaml"):
        with pytest.raises(ProjectPathError):
            resolve_workspace_path(workspace, bad)

    link = workspace / "escape.yaml"
    link.symlink_to(outside)
    with pytest.raises(ProjectPathError):
        resolve_workspace_path(workspace, "escape.yaml")


def test_project_loader_fails_closed_on_unknown_schema_extra_fields_and_dangling_component(
    tmp_path: Path,
) -> None:
    project_dir = tmp_path / "rover"
    create_studio_project(
        project_dir,
        project_id="rover-02",
        project_name="Rover 02",
        template="single-sim-motor",
    )

    manifest_file = project_dir / PROJECT_MANIFEST_FILENAME
    original = manifest_file.read_text(encoding="utf-8")

    # Unsupported schema_version fails closed.
    bad_version = yaml.safe_load(original)
    bad_version["schema_version"] = "99"
    manifest_file.write_text(yaml.safe_dump(bad_version, sort_keys=False))
    with pytest.raises(UnsupportedProjectSchemaVersionError):
        load_studio_project(project_dir)

    # Extra unknown field fails closed.
    manifest_file.write_text(original + "unexpected_field: true\n")
    with pytest.raises(ProjectValidationError):
        load_studio_project(project_dir)

    manifest_file.write_text(original)

    # Dangling component_id in graph fails cross-validation.
    graph_file = project_dir / "robot/connections/graph.yaml"
    graph_data = yaml.safe_load(graph_file.read_text(encoding="utf-8"))
    graph_data["nodes"][0]["component_id"] = "nonexistent_component"
    graph_file.write_text(yaml.safe_dump(graph_data, sort_keys=False))
    with pytest.raises(ProjectValidationError, match="unknown robot component"):
        load_studio_project(project_dir)


def test_atomic_write_and_template_guardrails(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    written = atomic_write_text(workspace, "robot/notes.txt", "hello\n")
    assert written.read_text(encoding="utf-8") == "hello\n"
    assert list((workspace / "robot").glob(".*.tmp")) == []

    with pytest.raises(ProjectTemplateError):
        create_studio_project(
            tmp_path / "bad-template",
            project_id="x",
            project_name="X",
            template="does-not-exist",
        )

    non_empty = tmp_path / "existing"
    non_empty.mkdir()
    (non_empty / "file.txt").write_text("occupied", encoding="utf-8")
    with pytest.raises(ProjectTemplateError, match="not empty"):
        create_studio_project(
            non_empty,
            project_id="x",
            project_name="X",
            template="blank-robot",
        )
