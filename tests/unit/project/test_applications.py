import pytest

from hiyelx.config.v2.loader import load_robot_config
from hiyelx.project import (
    ApplicationMetadata,
    ApplicationWorkflowDocument,
    ProjectValidationError,
    UnsupportedProjectSchemaVersionError,
    WorkflowFaultPolicy,
    WorkflowTask,
    load_workflow_from_str,
    serialize_workflow_yaml,
    validate_workflow_against_robot,
)


def test_workflow_round_trip_and_robot_config_cross_validation() -> None:
    robot = load_robot_config("examples/configs/mock-robot.yaml")
    workflow = ApplicationWorkflowDocument(
        schema_version="1",
        application=ApplicationMetadata(
            id="rover-inspection",
            name="Rover Sensor & Drive Check",
            version="0.1.0",
        ),
        tasks=(
            WorkflowTask(
                id="read_encoder",
                name="Verify Wheel Encoder",
                target_component="wheel_encoder",
                action="read_state",
                timeout_ms=1000,
                on_fault=WorkflowFaultPolicy.ABORT,
                next_tasks=("drive_forward",),
            ),
            WorkflowTask(
                id="drive_forward",
                name="Command Drive Velocity",
                target_component="drive_motor",
                action="set_velocity",
                parameters={"velocity_rad_s": 0.5},
                timeout_ms=2000,
                on_fault=WorkflowFaultPolicy.SAFE_STOP,
                next_tasks=("capture_view",),
            ),
            WorkflowTask(
                id="capture_view",
                name="Capture Front Camera Frame",
                target_component="front_camera",
                action="capture_frame",
                timeout_ms=1500,
                on_fault=WorkflowFaultPolicy.DEGRADE,
            ),
        ),
    )

    yaml_text = serialize_workflow_yaml(workflow)
    reloaded = load_workflow_from_str(yaml_text)
    assert reloaded == workflow
    validate_workflow_against_robot(reloaded, robot)


def test_workflow_fails_closed_on_bad_schema_unknown_next_or_unknown_component() -> None:
    robot = load_robot_config("examples/configs/mock-robot.yaml")

    with pytest.raises(UnsupportedProjectSchemaVersionError):
        load_workflow_from_str('schema_version: "2"\napplication:\n  id: x\n  name: X\n')

    with pytest.raises(ProjectValidationError):
        load_workflow_from_str(
            """
schema_version: "1"
application:
  id: bad
  name: Bad Workflow
tasks:
  - id: step1
    name: Step 1
    target_component: drive_motor
    action: set_velocity
    next_tasks: ["does_not_exist"]
"""
        )

    dangling = load_workflow_from_str(
        """
schema_version: "1"
application:
  id: dangling
  name: Dangling Component
tasks:
  - id: step1
    name: Step 1
    target_component: missing_arm
    action: set_velocity
"""
    )
    with pytest.raises(ProjectValidationError, match="missing_arm"):
        validate_workflow_against_robot(dangling, robot)
