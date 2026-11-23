from pathlib import Path

import pytest

from hiyelx.cli import FAILURE, SUCCESS, main

EXAMPLES_DIR = Path(__file__).parents[2] / "examples/configs"
MOCK_ROBOT_CONFIG = EXAMPLES_DIR / "mock-robot.yaml"
SIM_MOTOR_CONFIG = EXAMPLES_DIR / "sim-motor.yaml"


def test_cli_validate_v2_robot_config(capsys: pytest.CaptureFixture[str]) -> None:
    exit_code = main(["validate-config", str(MOCK_ROBOT_CONFIG)])
    assert exit_code == SUCCESS

    captured = capsys.readouterr()
    assert "configuration=valid" in captured.out


def test_cli_validate_v1_config(capsys: pytest.CaptureFixture[str]) -> None:
    exit_code = main(["validate-config", str(SIM_MOTOR_CONFIG)])
    assert exit_code == SUCCESS

    captured = capsys.readouterr()
    assert "configuration=valid" in captured.out


def test_cli_run_mock_robot(capsys: pytest.CaptureFixture[str]) -> None:
    exit_code = main(["run", str(MOCK_ROBOT_CONFIG)])
    assert exit_code == SUCCESS

    captured = capsys.readouterr()
    assert "robot=running id=hiyelx-mock-rover-01" in captured.out
    assert "name=HIYELX Canonical Simulation Rover" in captured.out
    assert "components=wheel_encoder,drive_motor,base_imu,front_camera" in captured.out
    assert "startup=succeeded" in captured.out
    assert "shutdown=succeeded" in captured.out


def test_cli_run_v1_backward_compatibility(capsys: pytest.CaptureFixture[str]) -> None:
    exit_code = main(["run", str(SIM_MOTOR_CONFIG)])
    assert exit_code == SUCCESS

    captured = capsys.readouterr()
    assert "runtime=running" in captured.out
    assert "resources=sim_motor" in captured.out
    assert "startup=succeeded" in captured.out
    assert "shutdown=succeeded" in captured.out


def test_cli_run_invalid_config_fails(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    bad_config = tmp_path / "bad.yaml"
    bad_config.write_text("invalid: yaml: syntax: [", encoding="utf-8")

    exit_code = main(["run", str(bad_config)])
    assert exit_code == FAILURE

    captured = capsys.readouterr()
    assert "error: configuration is invalid" in captured.err


def test_cli_run_with_duration(capsys: pytest.CaptureFixture[str]) -> None:
    exit_code = main(["run", str(MOCK_ROBOT_CONFIG), "--duration", "0.01"])
    assert exit_code == SUCCESS

    captured = capsys.readouterr()
    assert "startup=succeeded" in captured.out
    assert "shutdown=succeeded" in captured.out
