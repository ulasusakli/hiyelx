import asyncio
import json
from pathlib import Path

import pytest

from hiyelx import cli
from hiyelx.resources import HealthStatus, LifecycleState, ResourceIdentity
from hiyelx.rpc import MotorGrpcServer, RpcTransportState
from hiyelx.runtime import (
    RuntimeEventOperation,
    RuntimeEventOutcome,
    RuntimeManager,
    RuntimeManagerState,
)
from hiyelx.runtime.control import (
    ControlProtocolError,
    InvalidSessionIdError,
    PreviewReply,
    ResourceStatus,
    RuntimeCliExitCode,
    RuntimePreviewUnavailableError,
    RuntimePreviewUnsupportedError,
    SessionNotRunningError,
    StatusReply,
    StopReply,
    UnsafeSessionPathError,
    UnsupportedPlatformError,
)
from hiyelx.runtime.history import (
    EventRecord,
    HistoryStoreError,
    RunNotFoundError,
    RunRecord,
    RunResult,
    StopReason,
)
from hiyelx.simulation import (
    SimulatedMotor,
    SimulationMotorPreviewState,
    SimulationPreviewResourceSnapshot,
    SimulationPreviewSnapshot,
)

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


def test_runtime_preview_dispatch_emits_only_canonical_snapshot(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []
    snapshot = SimulationPreviewSnapshot(
        schema_version="1",
        runtime_state=RuntimeManagerState.RUNNING,
        resources=(
            SimulationPreviewResourceSnapshot(
                identity=ResourceIdentity("sim_motor"),
                kind="motor",
                lifecycle_state=LifecycleState.RUNNING,
                health_status=HealthStatus.HEALTHY,
                health_summary=None,
                state=SimulationMotorPreviewState(1.5, 0.5, 2.0, 3),
            ),
        ),
    )

    async def fake_preview(session: str) -> PreviewReply:
        calls.append(session)
        assert session == "alpha"
        return PreviewReply("alpha", snapshot)

    monkeypatch.setattr(cli, "request_preview", fake_preview)

    assert (
        cli.main(["runtime", "preview", "--session", "alpha"])
        == RuntimeCliExitCode.SUCCESS
    )
    captured = capsys.readouterr()
    assert captured.err == ""
    assert captured.out == (
        '{"resources":[{"health_status":"healthy","health_summary":null,'
        '"identity":"sim_motor","kind":"motor","lifecycle_state":"running",'
        '"state":{"angular_position_radians":1.5,'
        '"angular_velocity_radians_per_second":0.5,"revision":3,'
        '"simulation_time_seconds":2.0}}],"runtime_state":"running",'
        '"schema_version":"1"}\n'
    )
    assert calls == ["alpha"]
    assert "alpha" not in captured.out


@pytest.mark.parametrize(
    ("error", "exit_code", "message"),
    (
        (
            InvalidSessionIdError(),
            RuntimeCliExitCode.INVALID_SESSION_ID,
            "runtime session ID is invalid",
        ),
        (
            SessionNotRunningError(),
            RuntimeCliExitCode.SESSION_NOT_RUNNING,
            "runtime session is not running",
        ),
        (
            ControlProtocolError("private protocol detail"),
            RuntimeCliExitCode.CONTROL_PROTOCOL_FAILURE,
            "runtime control failed",
        ),
        (
            UnsafeSessionPathError("private path"),
            RuntimeCliExitCode.CONTROL_PROTOCOL_FAILURE,
            "runtime control failed",
        ),
        (
            OSError("private local I/O detail"),
            RuntimeCliExitCode.CONTROL_PROTOCOL_FAILURE,
            "runtime control failed",
        ),
        (
            UnsupportedPlatformError(),
            RuntimeCliExitCode.UNSUPPORTED_PLATFORM,
            "runtime control is unsupported on this platform",
        ),
        (
            RuntimePreviewUnavailableError(),
            RuntimeCliExitCode.PREVIEW_UNAVAILABLE,
            "runtime preview is unavailable",
        ),
        (
            RuntimePreviewUnsupportedError(),
            RuntimeCliExitCode.PREVIEW_UNSUPPORTED,
            "runtime preview is unsupported",
        ),
    ),
)
def test_runtime_preview_failures_are_exact_and_sanitized(
    error: Exception,
    exit_code: RuntimeCliExitCode,
    message: str,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fail(_session: str) -> PreviewReply:
        raise error

    monkeypatch.setattr(cli, "request_preview", fail)

    assert cli.main(["runtime", "preview", "--session", "alpha"]) == exit_code
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == f"error: {message}\n"
    assert "private" not in captured.err


def test_runtime_preview_rejects_text_and_json_modes(
    capsys: pytest.CaptureFixture[str],
) -> None:
    for arguments in (
        ["runtime", "preview", "--session", "alpha", "--json"],
        ["runtime", "preview", "--session", "alpha", "text"],
    ):
        with pytest.raises(SystemExit) as caught:
            cli.main(arguments)
        assert caught.value.code == RuntimeCliExitCode.INVALID_CONFIGURATION
        captured = capsys.readouterr()
        assert captured.out == ""
        assert "usage:" in captured.err


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


def test_runtime_runs_prune_parser_and_exact_output(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    keeps: list[int] = []

    def fake_prune(*, keep: int) -> int:
        keeps.append(keep)
        return 3 if keep == 0 else 0

    monkeypatch.setattr(cli, "prune_runs", fake_prune)
    assert (
        cli.main(["runtime", "runs", "prune", "--keep", "0"])
        == RuntimeCliExitCode.SUCCESS
    )
    captured = capsys.readouterr()
    assert captured.out == "deleted-runs=3\n"
    assert captured.err == ""

    maximum = str((1 << 63) - 1)
    assert (
        cli.main(["runtime", "runs", "prune", "--keep", maximum])
        == RuntimeCliExitCode.SUCCESS
    )
    captured = capsys.readouterr()
    assert captured.out == "deleted-runs=0\n"
    assert captured.err == ""
    assert keeps == [0, (1 << 63) - 1]


@pytest.mark.parametrize(
    "arguments",
    (
        ("runtime", "runs", "prune"),
        ("runtime", "runs", "prune", "--keep", "-1"),
        ("runtime", "runs", "prune", "--keep", str(1 << 63)),
        ("runtime", "runs", "prune", "--keep", "not-an-integer"),
    ),
)
def test_runtime_runs_prune_rejects_invalid_arguments(
    capsys: pytest.CaptureFixture[str],
    arguments: tuple[str, ...],
) -> None:
    with pytest.raises(SystemExit) as caught:
        cli.main(list(arguments))
    assert caught.value.code == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "usage:" in captured.err


def test_runtime_runs_prune_history_failure_is_fixed_and_sanitized(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_prune(*, keep: int) -> int:
        assert keep == 1
        raise HistoryStoreError("private sqlite path /secret/history.sqlite3")

    monkeypatch.setattr(cli, "prune_runs", fail_prune)
    assert (
        cli.main(["runtime", "runs", "prune", "--keep", "1"])
        == RuntimeCliExitCode.HISTORY_STORE_FAILURE
    )
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "error: runtime history failed\n"
    assert "private" not in captured.err
    assert "sqlite" not in captured.err
    assert "secret" not in captured.err


def test_runtime_events_text_cursor_limit_and_canonical_json(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    records = _event_records()
    calls: list[tuple[str, int, int]] = []

    def fake_list_events(
        run_id: str,
        *,
        after: int,
        limit: int,
    ) -> tuple[EventRecord, ...]:
        calls.append((run_id, after, limit))
        return records

    monkeypatch.setattr(cli, "list_events", fake_list_events)
    run_id = records[0].run_id
    assert (
        cli.main(["runtime", "events", "--run", run_id])
        == RuntimeCliExitCode.SUCCESS
    )
    captured = capsys.readouterr()
    assert calls == [(run_id, -1, 100)]
    assert captured.err == ""
    assert captured.out == (
        f"run={run_id}\n"
        "event-count=2\n"
        "event=0 type=runtime_start outcome=requested severity=info "
        "resource=none lifecycle=none health=none "
        "recorded-at=2026-10-18T10:11:12.123456Z "
        "summary=runtime start requested\n"
        "event=1 type=resource_start outcome=succeeded severity=info "
        "resource=sim_motor lifecycle=running health=healthy "
        "recorded-at=2026-10-18T10:11:13.123456Z "
        "summary=resource start succeeded\n"
    )

    assert (
        cli.main(
            [
                "runtime",
                "events",
                "--run",
                run_id,
                "--after",
                "0",
                "--limit",
                "1",
                "--json",
            ]
        )
        == RuntimeCliExitCode.SUCCESS
    )
    captured = capsys.readouterr()
    assert calls[-1] == (run_id, 0, 1)
    document = json.loads(captured.out)
    assert document == {
        "event_count": 2,
        "events": [cli._event_document(record) for record in records],  # pyright: ignore[reportPrivateUsage]
        "run_id": run_id,
    }
    assert captured.out == json.dumps(
        document,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ) + "\n"


@pytest.mark.parametrize(
    ("option", "value", "message"),
    (
        ("--after", "-2", "after must be an integer at or above -1"),
        ("--after", "true", "after must be an integer at or above -1"),
        ("--limit", "0", "limit must be between 1 and 1000"),
        ("--limit", "1001", "limit must be between 1 and 1000"),
    ),
)
def test_runtime_events_rejects_invalid_cursor_and_limit(
    option: str,
    value: str,
    message: str,
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as caught:
        cli.main(["runtime", "events", "--run", _run_record().run_id, option, value])
    assert caught.value.code == RuntimeCliExitCode.INVALID_CONFIGURATION
    captured = capsys.readouterr()
    assert captured.out == ""
    assert message in captured.err


def test_runtime_events_errors_are_fixed_sanitized_and_emit_no_partial_output(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def missing(
        _run_id: str,
        *,
        after: int,
        limit: int,
    ) -> tuple[EventRecord, ...]:
        del after, limit
        raise RunNotFoundError("private run")

    monkeypatch.setattr(cli, "list_events", missing)
    assert (
        cli.main(["runtime", "events", "--run", "not-a-run"])
        == RuntimeCliExitCode.RUN_NOT_FOUND
    )
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "error: runtime run is not found\n"
    assert "private" not in captured.err

    def corrupt(
        _run_id: str,
        *,
        after: int,
        limit: int,
    ) -> tuple[EventRecord, ...]:
        del after, limit
        raise HistoryStoreError("/private/store sqlite payload")

    monkeypatch.setattr(cli, "list_events", corrupt)
    assert (
        cli.main(["runtime", "events", "--run", _run_record().run_id])
        == RuntimeCliExitCode.HISTORY_STORE_FAILURE
    )
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


def _event_records() -> tuple[EventRecord, ...]:
    run_id = _run_record().run_id
    return (
        EventRecord(
            schema_version=1,
            run_id=run_id,
            sequence=0,
            resource_identity=None,
            event_type=RuntimeEventOperation.RUNTIME_START,
            outcome=RuntimeEventOutcome.REQUESTED,
            severity="info",
            summary="runtime start requested",
            lifecycle_state=None,
            health_status=None,
            recorded_at="2026-10-18T10:11:12.123456Z",
        ),
        EventRecord(
            schema_version=1,
            run_id=run_id,
            sequence=1,
            resource_identity=ResourceIdentity("sim_motor"),
            event_type=RuntimeEventOperation.RESOURCE_START,
            outcome=RuntimeEventOutcome.SUCCEEDED,
            severity="info",
            summary="resource start succeeded",
            lifecycle_state=LifecycleState.RUNNING,
            health_status=HealthStatus.HEALTHY,
            recorded_at="2026-10-18T10:11:13.123456Z",
        ),
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
