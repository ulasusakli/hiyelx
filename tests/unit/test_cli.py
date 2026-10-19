import asyncio
import json
from pathlib import Path

import pytest

from hiyelx import cli
from hiyelx.resources import HealthStatus, LifecycleState, ResourceIdentity
from hiyelx.rpc import MotorGrpcServer, RpcTransportState
from hiyelx.runtime import RuntimeManager, RuntimeManagerState
from hiyelx.runtime.control import (
    ResourceStatus,
    RuntimeCliExitCode,
    SessionNotRunningError,
    StatusReply,
    StopReply,
)
from hiyelx.runtime.history import (
    HistoryStoreError,
    RunNotFoundError,
    RunRecord,
    RunResult,
    StopReason,
)
from hiyelx.simulation import SimulatedMotor

EXPECTED_TRANSCRIPT = tuple(
    (
        Path(__file__).parents[2] / "examples/expected/sim-motor.txt"
    ).read_text(encoding="utf-8").splitlines()
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
    assert "scaffold" in help_output
    assert "hardware" in help_output
    assert "runtime" in help_output

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


def test_runtime_status_and_stop_dispatch_with_canonical_output(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    identity = ResourceIdentity("sim_motor")

    async def fake_status(session: str) -> StatusReply:
        assert session == "alpha"
        return StatusReply(
            session="alpha",
            manager_state=RuntimeManagerState.RUNNING,
            resources=(
                ResourceStatus(
                    identity,
                    LifecycleState.RUNNING,
                    HealthStatus.HEALTHY,
                    None,
                ),
            ),
            successful_start_order=(identity,),
            active_resource_order=(identity,),
            event_high_water_mark=3,
            latest_event_summary="runtime running",
        )

    async def fake_stop(session: str) -> StopReply:
        assert session == "alpha"
        return StopReply("alpha")

    monkeypatch.setattr(cli, "request_status", fake_status)
    monkeypatch.setattr(cli, "request_stop", fake_stop)

    assert cli.main(["runtime", "status", "--session", "alpha"]) == 0
    captured = capsys.readouterr()
    assert captured.err == ""
    assert captured.out == (
        "session=alpha\n"
        "manager-state=running\n"
        "resource-count=1\n"
        "resource=sim_motor lifecycle=running health=healthy health-summary=none\n"
        "successful-start-order=sim_motor\n"
        "active-resource-order=sim_motor\n"
        "event-high-water-mark=3\n"
        "latest-event=runtime running\n"
    )

    assert cli.main(["runtime", "stop", "--session", "alpha"]) == 0
    captured = capsys.readouterr()
    assert captured.out == "session=alpha\nruntime=stopped\n"
    assert captured.err == ""


def test_runtime_cli_validation_and_missing_session_are_sanitized(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert (
        cli.main(["runtime", "status", "--session", "../private"])
        == RuntimeCliExitCode.INVALID_SESSION_ID
    )
    captured = capsys.readouterr()
    assert captured.err == "error: runtime session ID is invalid\n"
    assert "private" not in captured.err

    async def missing(_session: str) -> StatusReply:
        raise SessionNotRunningError

    monkeypatch.setattr(cli, "request_status", missing)
    assert (
        cli.main(["runtime", "status", "--session", "missing"])
        == RuntimeCliExitCode.SESSION_NOT_RUNNING
    )
    captured = capsys.readouterr()
    assert captured.err == "error: runtime session is not running\n"

    invalid = tmp_path / "secret-config.yaml"
    invalid.write_text("credential: top-secret", encoding="utf-8")
    assert (
        cli.main(
            ["runtime", "start", str(invalid), "--session", "alpha"]
        )
        == RuntimeCliExitCode.INVALID_CONFIGURATION
    )
    captured = capsys.readouterr()
    assert captured.err == "error: runtime configuration is invalid\n"
    assert "secret" not in captured.err
    assert str(invalid) not in captured.err


def test_runtime_runs_list_text_limit_and_canonical_json(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    record = _run_record()
    limits: list[int] = []

    def fake_list_runs(*, limit: int) -> tuple[RunRecord, ...]:
        limits.append(limit)
        return (record,)

    monkeypatch.setattr(cli, "list_runs", fake_list_runs)
    assert cli.main(["runtime", "runs", "list"]) == RuntimeCliExitCode.SUCCESS
    captured = capsys.readouterr()
    assert limits == [20]
    assert captured.err == ""
    assert captured.out == (
        "run-count=1\n"
        f"run={record.run_id} session=alpha result=completed "
        f"started-at={record.started_at} ended-at={record.ended_at} "
        "event-high-water-mark=3\n"
    )

    assert (
        cli.main(["runtime", "runs", "list", "--limit", "1", "--json"])
        == RuntimeCliExitCode.SUCCESS
    )
    captured = capsys.readouterr()
    assert limits == [20, 1]
    assert captured.err == ""
    document = json.loads(captured.out)
    assert document == {"run_count": 1, "runs": [cli._run_document(record)]}  # pyright: ignore[reportPrivateUsage]
    assert captured.out == json.dumps(
        document,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ) + "\n"


@pytest.mark.parametrize("limit", ("0", "101", "true"))
def test_runtime_runs_list_rejects_invalid_limits(
    limit: str,
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as caught:
        cli.main(["runtime", "runs", "list", "--limit", limit])
    assert caught.value.code == RuntimeCliExitCode.INVALID_CONFIGURATION
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "limit must be between 1 and 100" in captured.err


def test_runtime_runs_show_complete_and_incomplete(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    complete = _run_record()

    def get_complete(_run_id: str) -> RunRecord:
        return complete

    monkeypatch.setattr(cli, "get_run", get_complete)
    assert (
        cli.main(["runtime", "runs", "show", complete.run_id])
        == RuntimeCliExitCode.SUCCESS
    )
    captured = capsys.readouterr()
    assert captured.err == ""
    assert captured.out == "\n".join(cli._render_run(complete)) + "\n"  # pyright: ignore[reportPrivateUsage]

    incomplete = RunRecord(
        complete.schema_version,
        complete.run_id,
        complete.session_id,
        complete.config_fingerprint,
        complete.package_version,
        complete.platform,
        complete.started_at,
        None,
        None,
        None,
        None,
    )
    def get_incomplete(_run_id: str) -> RunRecord:
        return incomplete

    monkeypatch.setattr(cli, "get_run", get_incomplete)
    assert (
        cli.main(["runtime", "runs", "show", incomplete.run_id, "--json"])
        == RuntimeCliExitCode.SUCCESS
    )
    captured = capsys.readouterr()
    assert captured.err == ""
    assert json.loads(captured.out)["result"] is None
    assert "ended-at=none" in "\n".join(cli._render_run(incomplete))  # pyright: ignore[reportPrivateUsage]
    assert "result=incomplete" in "\n".join(cli._render_run(incomplete))  # pyright: ignore[reportPrivateUsage]


def test_runtime_runs_errors_are_fixed_and_sanitized(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def missing(_run_id: str) -> RunRecord:
        raise RunNotFoundError("private-id")

    monkeypatch.setattr(cli, "get_run", missing)
    assert (
        cli.main(["runtime", "runs", "show", "not-a-uuid"])
        == RuntimeCliExitCode.RUN_NOT_FOUND
    )
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "error: runtime run is not found\n"
    assert "private" not in captured.err

    def corrupt(*, limit: int) -> tuple[RunRecord, ...]:
        del limit
        raise HistoryStoreError("/private/path database malformed")

    monkeypatch.setattr(cli, "list_runs", corrupt)
    assert cli.main(["runtime", "runs", "list"]) == 10
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "error: runtime history failed\n"
    assert "private" not in captured.err


def test_hardware_preflight_is_deterministic_and_does_not_expose_transport(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config_path = tmp_path / "hardware-acceptance.yaml"
    config_path.write_text(
        """\
schema_version: "1"
driver_identity: motor.dynamixel.xl430_w250_t
expected_motor_model: XL430-W250-T
transport_identifier: private-device-credential-token
device_id: 1
baud_rate: 57600
command_bounds:
  minimum_rad_s: -0.3
  maximum_rad_s: 0.3
operation_deadline_seconds: 2.0
movement_authorized: false
evidence_session_id: hca-hw0-preflight
""",
        encoding="utf-8",
    )

    assert cli.main(["hardware", "preflight", str(config_path)]) == cli.SUCCESS
    first = capsys.readouterr()
    assert cli.main(["hardware", "preflight", str(config_path)]) == cli.SUCCESS
    second = capsys.readouterr()

    assert first.out == second.out
    assert first.err == ""
    assert "acceptance-preflight=valid" in first.out
    assert "physical-operation-authorized=false" in first.out
    assert "device-operations=none" in first.out
    assert "private-device" not in first.out
    assert "credential" not in first.out
    assert "token" not in first.out


def _run_record() -> RunRecord:
    return RunRecord(
        schema_version=1,
        run_id="11111111-1111-4111-8111-111111111111",
        session_id="alpha",
        config_fingerprint="a" * 64,
        package_version="0.2.0a1",
        platform="linux",
        started_at="2026-10-18T10:11:12.123456Z",
        ended_at="2026-10-18T10:12:13.123456Z",
        result=RunResult.COMPLETED,
        stop_reason=StopReason.CLI_STOP,
        event_high_water_mark=3,
    )


def test_hardware_preflight_failure_is_sanitized(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config_path = tmp_path / "secret-hardware-config.yaml"
    config_path.write_text("credential: top-secret", encoding="utf-8")

    assert cli.main(["hardware", "preflight", str(config_path)]) == cli.FAILURE
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "error: hardware acceptance preflight failed\n"
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


def test_motor_driver_scaffold_cli_creates_files(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    output = tmp_path / "acme-driver"

    assert (
        cli.main(
            [
                "scaffold",
                "motor-driver",
                str(output),
                "--package-name",
                "acme_motor_driver",
                "--model-name",
                "motor.acme.reference",
            ]
        )
        == cli.SUCCESS
    )
    captured = capsys.readouterr()
    assert captured.out == (
        "scaffold=motor-driver\n"
        "package=acme_motor_driver\n"
        "model=motor.acme.reference\n"
        "files=6\n"
    )
    assert captured.err == ""
    assert (output / "tests/test_driver.py").is_file()


def test_motor_driver_scaffold_cli_refuses_overwrite_without_path_disclosure(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    output = tmp_path / "private-driver"
    output.mkdir()

    assert (
        cli.main(
            [
                "scaffold",
                "motor-driver",
                str(output),
                "--package-name",
                "acme_motor_driver",
                "--model-name",
                "motor.acme.reference",
            ]
        )
        == cli.FAILURE
    )
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "error: motor-driver scaffold failed\n"
    assert str(output) not in captured.err
