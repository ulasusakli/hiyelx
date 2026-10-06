import asyncio
from pathlib import Path

import pytest

from hiyelx import cli
from hiyelx.rpc import MotorGrpcServer, RpcTransportState
from hiyelx.runtime import RuntimeManager, RuntimeManagerState
from hiyelx.simulation import SimulatedMotor

EXPECTED_TRANSCRIPT = (
    "demo=sim-motor",
    "configuration=valid",
    "runtime=running",
    "grpc=running",
    "motors=sim_motor",
    "command=positive velocity=2.000",
    "advance=1.250",
    "state=positive position=2.500 velocity=2.000",
    "command=negative velocity=-1.000",
    "advance=0.500",
    "state=negative position=2.000 velocity=-1.000",
    "command=zero velocity=0.000",
    "stop velocity=0.000",
    "cleanup grpc=stopped runtime=stopped",
)


def test_cli_help_and_demo_dispatch(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with pytest.raises(SystemExit) as caught:
        cli.main(["--help"])
    assert caught.value.code == 0
    help_output = capsys.readouterr().out
    assert "validate-config" in help_output
    assert "demo" in help_output

    async def fake_demo() -> tuple[str, ...]:
        return ("demo=dispatched",)

    monkeypatch.setattr(cli, "run_sim_motor_demo", fake_demo)
    assert cli.main(["demo", "sim-motor"]) == cli.SUCCESS
    assert capsys.readouterr().out == "demo=dispatched\n"


def test_validate_config_success(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    config_path = tmp_path / "runtime.yaml"
    config_path.write_text(
        'schema_version: "1"\nresources: []\n',
        encoding="utf-8",
    )

    assert cli.main(["validate-config", str(config_path)]) == cli.SUCCESS
    captured = capsys.readouterr()
    assert captured.out == "configuration=valid\n"
    assert captured.err == ""


def test_validate_config_failure_is_sanitized(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config_path = tmp_path / "secret-device-config.yaml"
    config_path.write_text("credential: top-secret", encoding="utf-8")

    assert cli.main(["validate-config", str(config_path)]) == cli.FAILURE
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "error: configuration is invalid\n"
    assert "top-secret" not in captured.err
    assert str(config_path) not in captured.err


def test_sim_motor_demo_transcript_and_repeated_runs_are_deterministic() -> None:
    first = asyncio.run(cli.run_sim_motor_demo())
    second = asyncio.run(cli.run_sim_motor_demo())

    assert first == EXPECTED_TRANSCRIPT
    assert second == first


def test_sim_motor_demo_cleanup_after_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    grpc_cleanup: list[RpcTransportState] = []
    runtime_cleanup: list[RuntimeManagerState] = []
    original_stop_transport = MotorGrpcServer.stop_transport
    original_shutdown = RuntimeManager.shutdown

    async def stop_transport(server: MotorGrpcServer) -> None:
        await original_stop_transport(server)
        grpc_cleanup.append(server.state)

    async def shutdown(runtime: RuntimeManager) -> None:
        await original_shutdown(runtime)
        runtime_cleanup.append(runtime.state)

    monkeypatch.setattr(MotorGrpcServer, "stop_transport", stop_transport)
    monkeypatch.setattr(RuntimeManager, "shutdown", shutdown)

    assert asyncio.run(cli.run_sim_motor_demo()) == EXPECTED_TRANSCRIPT
    assert grpc_cleanup == [RpcTransportState.STOPPED]
    assert runtime_cleanup == [RuntimeManagerState.STOPPED]


def test_sim_motor_demo_cleanup_after_injected_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    grpc_cleanup: list[RpcTransportState] = []
    runtime_cleanup: list[RuntimeManagerState] = []
    original_stop_transport = MotorGrpcServer.stop_transport
    original_shutdown = RuntimeManager.shutdown

    def fail_advance(motor: SimulatedMotor, time_step_seconds: float) -> None:
        del motor, time_step_seconds
        raise RuntimeError("injected secret failure")

    async def stop_transport(server: MotorGrpcServer) -> None:
        await original_stop_transport(server)
        grpc_cleanup.append(server.state)

    async def shutdown(runtime: RuntimeManager) -> None:
        await original_shutdown(runtime)
        runtime_cleanup.append(runtime.state)

    monkeypatch.setattr(SimulatedMotor, "advance_time", fail_advance)
    monkeypatch.setattr(MotorGrpcServer, "stop_transport", stop_transport)
    monkeypatch.setattr(RuntimeManager, "shutdown", shutdown)

    with pytest.raises(RuntimeError, match="injected secret failure"):
        asyncio.run(cli.run_sim_motor_demo())

    assert grpc_cleanup == [RpcTransportState.STOPPED]
    assert runtime_cleanup == [RuntimeManagerState.STOPPED]


def test_cli_demo_failure_output_is_sanitized(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fail_demo() -> tuple[str, ...]:
        raise RuntimeError("secret /dev/private")

    monkeypatch.setattr(cli, "run_sim_motor_demo", fail_demo)
    assert cli.main(["demo", "sim-motor"]) == cli.FAILURE
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "error: sim-motor demo failed\n"
