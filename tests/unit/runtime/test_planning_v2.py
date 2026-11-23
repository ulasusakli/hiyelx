
from hiyelx.config.v2 import load_robot_config_from_str
from hiyelx.resources import ResourceIdentity
from hiyelx.runtime.planning import plan_startup

MOCK_ROBOT_YAML = """\
schema_version: "2"
robot:
  id: "test-bot"
  name: "Test Bot"
components:
  - id: "front_camera"
    category: "vision"
    model: "mock.camera"
    depends_on:
      - "base_imu"
  - id: "base_imu"
    category: "spatial"
    model: "mock.imu"
    depends_on:
      - "drive_motor"
  - id: "drive_motor"
    category: "actuator"
    model: "mock.motor"
    depends_on:
      - "wheel_encoder"
  - id: "wheel_encoder"
    category: "feedback"
    model: "mock.encoder"
"""


def test_plan_startup_v2_dependency_chain() -> None:
    config = load_robot_config_from_str(MOCK_ROBOT_YAML)
    order = plan_startup(config)

    assert order == (
        ResourceIdentity("wheel_encoder"),
        ResourceIdentity("drive_motor"),
        ResourceIdentity("base_imu"),
        ResourceIdentity("front_camera"),
    )


def test_plan_startup_v2_independent_tie_breaking() -> None:
    yaml_independent = """\
schema_version: "2"
robot:
  id: "test-bot"
  name: "Test Bot"
components:
  - id: "zeta_sensor"
    category: "feedback"
    model: "mock.encoder"
  - id: "alpha_sensor"
    category: "feedback"
    model: "mock.encoder"
  - id: "beta_sensor"
    category: "feedback"
    model: "mock.encoder"
"""
    config = load_robot_config_from_str(yaml_independent)
    order = plan_startup(config)

    assert order == (
        ResourceIdentity("alpha_sensor"),
        ResourceIdentity("beta_sensor"),
        ResourceIdentity("zeta_sensor"),
    )
