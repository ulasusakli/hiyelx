import json
import os
import select
import shutil
import signal
import socket
import stat
import subprocess
import sys
import tempfile
import time
from collections.abc import Iterator
from pathlib import Path
from typing import cast

import pytest

from hiyelx.runtime.control import MAX_MESSAGE_BYTES, RuntimeCliExitCode
from hiyelx.runtime.history import open_writer

_ROOT = Path(__file__).parents[2]
_CONFIG = _ROOT / "examples/configs/sim-motor.yaml"
_READY_LINES = ("session=alpha", "runtime=running", "control=ready")
_STATUS_OUTPUT = """\
session=alpha
manager-state=running
resource-count=1
resource=sim_motor lifecycle=running health=healthy health-summary=none
successful-start-order=sim_motor
active-resource-order=sim_motor
event-high-water-mark=3
latest-event=runtime running
"""
_PREVIEW_OUTPUT = (
    '{"resources":[{"health_status":"healthy","health_summary":null,'
    '"identity":"sim_motor","kind":"motor","lifecycle_state":"running",'
    '"state":{"angular_position_radians":0.0,'
    '"angular_velocity_radians_per_second":0.0,"revision":0,'
    '"simulation_time_seconds":0.0}}],"runtime_state":"running",'
    '"schema_version":"1"}\n'
)


def test_run_queries_handle_missing_store_without_creating_it(
    short_state_directory: Path,
) -> None:
    environment = _environment(short_state_directory)
    history_root = Path(environment["HIYELX_RUNTIME_HISTORY_DIR"])

    listing = _run("runs", "list", environment=environment)
    assert listing.returncode == RuntimeCliExitCode.SUCCESS
    assert listing.stdout == "run-count=0\n"
    assert listing.stderr == ""
    assert not history_root.exists()

    missing = _run("runs", "show", "not-a-uuid", environment=environment)
    assert missing.returncode == RuntimeCliExitCode.RUN_NOT_FOUND
    assert missing.stdout == ""
    assert missing.stderr == "error: runtime run is not found\n"
    assert not history_root.exists()

    events = _run("events", "--run", "not-a-uuid", environment=environment)
    assert events.returncode == RuntimeCliExitCode.RUN_NOT_FOUND
    assert events.stdout == ""
    assert events.stderr == "error: runtime run is not found\n"
    assert not history_root.exists()

    prune = _run("runs", "prune", "--keep", "0", environment=environment)
    assert prune.returncode == RuntimeCliExitCode.SUCCESS
    assert prune.stdout == "deleted-runs=0\n"
    assert prune.stderr == ""
    assert not history_root.exists()


@pytest.mark.skipif(sys.platform not in {"darwin", "linux"}, reason="Unix sockets required")
def test_cross_process_start_status_stop_and_duplicate_start(
    short_state_directory: Path,
) -> None:
    state = short_state_directory
    environment = _environment(state)
    owner = _start_owner(environment)
    try:
        assert _read_lines(owner, 3) == _READY_LINES
        assert stat.S_IMODE((state / "alpha").stat().st_mode) == 0o700
        for artifact in ("owner.lock", "manifest.json", "control.sock"):
            assert stat.S_IMODE((state / "alpha" / artifact).lstat().st_mode) == 0o600

        duplicate = _run(
            "start",
            str(_CONFIG),
            "--session",
            "alpha",
            environment=environment,
        )
        assert duplicate.returncode == RuntimeCliExitCode.SESSION_ALREADY_RUNNING
        assert duplicate.stdout == ""
        assert duplicate.stderr == "error: runtime session is already running\n"

        status = _run("status", "--session", "alpha", environment=environment)
        assert status.returncode == RuntimeCliExitCode.SUCCESS
        assert status.stdout == _STATUS_OUTPUT
        assert status.stderr == ""

        running_runs = _run("runs", "list", "--json", environment=environment)
        assert running_runs.returncode == RuntimeCliExitCode.SUCCESS
        running_document = json.loads(running_runs.stdout)
        assert running_document["run_count"] == 1
        running_run = running_document["runs"][0]
        assert running_run["session_id"] == "alpha"
        assert running_run["result"] is None
        run_id = cast(str, running_run["run_id"])
        active_events = _run(
            "events",
            "--run",
            run_id,
            "--json",
            environment=environment,
        )
        assert active_events.returncode == RuntimeCliExitCode.SUCCESS
        active_document = json.loads(active_events.stdout)
        assert active_document["run_id"] == run_id
        assert active_document["event_count"] == 4
        assert [event["sequence"] for event in active_document["events"]] == [
            0,
            1,
            2,
            3,
        ]

        _assert_protocol_rejections_do_not_stop_owner(state, owner)

        stop = _run("stop", "--session", "alpha", environment=environment)
        assert stop.returncode == RuntimeCliExitCode.SUCCESS
        assert stop.stdout == "session=alpha\nruntime=stopped\n"
        assert stop.stderr == ""

        assert owner.wait(timeout=10) == RuntimeCliExitCode.SUCCESS
        assert owner.stdout is not None
        assert owner.stdout.read() == "runtime=stopped\n"
        assert owner.stderr is not None
        assert owner.stderr.read() == ""
        assert not (state / "alpha").exists()

        completed = _run("runs", "show", run_id, environment=environment)
        assert completed.returncode == RuntimeCliExitCode.SUCCESS
        assert f"run={run_id}\n" in completed.stdout
        assert "result=completed\n" in completed.stdout
        assert "stop-reason=cli_stop\n" in completed.stdout
        assert "event-high-water-mark=11\n" in completed.stdout
        assert completed.stderr == ""
        completed_events = _run(
            "events",
            "--run",
            run_id,
            "--after",
            "3",
            environment=environment,
        )
        assert completed_events.returncode == RuntimeCliExitCode.SUCCESS
        assert completed_events.stdout.startswith(f"run={run_id}\nevent-count=8\n")
        assert "event=4 type=safe_stop outcome=requested" in completed_events.stdout
        assert "event=11 type=runtime_stopped outcome=succeeded" in completed_events.stdout
    finally:
        _stop_test_owner(owner)

    for command in ("status", "stop"):
        missing = _run(command, "--session", "alpha", environment=environment)
        assert missing.returncode == RuntimeCliExitCode.SESSION_NOT_RUNNING
        assert missing.stdout == ""
        assert missing.stderr == "error: runtime session is not running\n"


@pytest.mark.skipif(sys.platform not in {"darwin", "linux"}, reason="Unix sockets required")
def test_cross_process_preview_is_canonical_read_only_and_sanitized(
    short_state_directory: Path,
) -> None:
    state = short_state_directory
    environment = _environment(state)
    owner = _start_owner(environment, session="preview")
    try:
        assert _read_lines(owner, 3) == (
            "session=preview",
            "runtime=running",
            "control=ready",
        )
        running = json.loads(
            _run("runs", "list", "--json", environment=environment).stdout
        )["runs"]
        assert len(running) == 1
        run_id = cast(str, running[0]["run_id"])
        status_before = _run(
            "status", "--session", "preview", environment=environment
        ).stdout
        assert status_before.startswith("session=preview\nmanager-state=running\n")
        events_before = _run(
            "events", "--run", run_id, "--json", environment=environment
        ).stdout
        session_directory = state / "preview"
        entries_before = tuple(sorted(path.name for path in session_directory.iterdir()))
        socket_before = (session_directory / "control.sock").lstat()
        artifacts_before = {
            path.name: path.read_bytes()
            for path in session_directory.iterdir()
            if path.is_file() and path.name != "control.sock"
        }

        first = _run("preview", "--session", "preview", environment=environment)
        second = _run("preview", "--session", "preview", environment=environment)
        assert first.returncode == RuntimeCliExitCode.SUCCESS
        assert second.returncode == RuntimeCliExitCode.SUCCESS
        assert first.stdout == second.stdout == _PREVIEW_OUTPUT
        assert first.stderr == second.stderr == ""
        assert owner.poll() is None

        events_after = _run(
            "events", "--run", run_id, "--json", environment=environment
        ).stdout
        status_after = _run(
            "status", "--session", "preview", environment=environment
        ).stdout
        runs_after = json.loads(
            _run("runs", "list", "--json", environment=environment).stdout
        )["runs"]
        artifacts_after = {
            path.name: path.read_bytes()
            for path in session_directory.iterdir()
            if path.is_file() and path.name != "control.sock"
        }
        entries_after = tuple(sorted(path.name for path in session_directory.iterdir()))
        socket_after = (session_directory / "control.sock").lstat()
        assert status_after == status_before
        assert events_after == events_before
        assert runs_after == running
        assert artifacts_after == artifacts_before
        assert entries_after == entries_before
        assert (socket_after.st_mode, socket_after.st_ino) == (
            socket_before.st_mode,
            socket_before.st_ino,
        )

        invalid = _run(
            "preview", "--session", "../private", environment=environment
        )
        assert invalid.returncode == RuntimeCliExitCode.INVALID_SESSION_ID
        assert invalid.stdout == ""
        assert invalid.stderr == "error: runtime session ID is invalid\n"

        stopped = _run("stop", "--session", "preview", environment=environment)
        assert stopped.returncode == RuntimeCliExitCode.SUCCESS
        assert owner.wait(timeout=10) == RuntimeCliExitCode.SUCCESS
        assert owner.stdout is not None
        assert owner.stdout.read() == "runtime=stopped\n"
        assert owner.stderr is not None
        assert owner.stderr.read() == ""
        assert not session_directory.exists()
    finally:
        _stop_test_owner(owner)

    missing = _run("preview", "--session", "preview", environment=environment)
    assert missing.returncode == RuntimeCliExitCode.SESSION_NOT_RUNNING
    assert missing.stdout == ""
    assert missing.stderr == "error: runtime session is not running\n"


@pytest.mark.skipif(sys.platform not in {"darwin", "linux"}, reason="Unix sockets required")
def test_prune_preserves_active_owner_and_newest_finalized_run(
    short_state_directory: Path,
) -> None:
    state = short_state_directory
    environment = _environment(state)

    def complete_session(session: str) -> str:
        owner = _start_owner(environment, session=session)
        try:
            assert _read_lines(owner, 3) == (
                f"session={session}",
                "runtime=running",
                "control=ready",
            )
            runs = json.loads(
                _run("runs", "list", "--json", environment=environment).stdout
            )["runs"]
            run_id = cast(
                str,
                next(run["run_id"] for run in runs if run["session_id"] == session),
            )
            stopped = _run("stop", "--session", session, environment=environment)
            assert stopped.returncode == RuntimeCliExitCode.SUCCESS
            assert owner.wait(timeout=10) == RuntimeCliExitCode.SUCCESS
            return run_id
        finally:
            _stop_test_owner(owner)

    old_run = complete_session("prune-old")
    newest_finalized = complete_session("prune-new")
    active = _start_owner(environment, session="prune-active")
    try:
        assert _read_lines(active, 3) == (
            "session=prune-active",
            "runtime=running",
            "control=ready",
        )
        runs = json.loads(
            _run("runs", "list", "--json", environment=environment).stdout
        )["runs"]
        active_run = cast(
            str,
            next(
                run["run_id"]
                for run in runs
                if run["session_id"] == "prune-active"
            ),
        )
        assert next(run for run in runs if run["run_id"] == active_run)["result"] is None

        pruned = _run("runs", "prune", "--keep", "1", environment=environment)
        assert pruned.returncode == RuntimeCliExitCode.SUCCESS
        assert pruned.stdout == "deleted-runs=1\n"
        assert pruned.stderr == ""
        assert active.poll() is None

        for command in (
            ("runs", "show", old_run),
            ("events", "--run", old_run),
        ):
            missing = _run(*command, environment=environment)
            assert missing.returncode == RuntimeCliExitCode.RUN_NOT_FOUND
            assert missing.stdout == ""
            assert missing.stderr == "error: runtime run is not found\n"

        retained_events = _run(
            "events",
            "--run",
            newest_finalized,
            "--json",
            environment=environment,
        )
        assert retained_events.returncode == RuntimeCliExitCode.SUCCESS
        assert json.loads(retained_events.stdout)["event_count"] == 12
        active_events = _run(
            "events",
            "--run",
            active_run,
            "--json",
            environment=environment,
        )
        assert active_events.returncode == RuntimeCliExitCode.SUCCESS
        assert json.loads(active_events.stdout)["event_count"] == 4

        stopped = _run(
            "stop",
            "--session",
            "prune-active",
            environment=environment,
        )
        assert stopped.returncode == RuntimeCliExitCode.SUCCESS
        assert active.wait(timeout=10) == RuntimeCliExitCode.SUCCESS
        final_runs = json.loads(
            _run("runs", "list", "--json", environment=environment).stdout
        )["runs"]
        assert {run["run_id"] for run in final_runs} == {
            newest_finalized,
            active_run,
        }
        assert all(run["result"] == "completed" for run in final_runs)
        for session in ("prune-old", "prune-new", "prune-active"):
            assert not (state / session).exists()
    finally:
        _stop_test_owner(active)


@pytest.mark.skipif(sys.platform not in {"darwin", "linux"}, reason="Unix sockets required")
def test_two_different_sessions_share_history_and_stop_independently(
    short_state_directory: Path,
) -> None:
    state = short_state_directory
    environment = _environment(state)
    history_root = Path(environment["HIYELX_RUNTIME_HISTORY_DIR"])
    bootstrap = open_writer(root=history_root)
    bootstrap.close()
    alpha = _start_owner(environment, session="session-alpha")
    beta: subprocess.Popen[str] | None = None
    try:
        assert _read_lines(alpha, 3) == (
            "session=session-alpha",
            "runtime=running",
            "control=ready",
        )
        beta = _start_owner(environment, session="session-beta")
        assert _read_lines(beta, 3) == (
            "session=session-beta",
            "runtime=running",
            "control=ready",
        )

        listing = _run("runs", "list", "--json", environment=environment)
        assert listing.returncode == RuntimeCliExitCode.SUCCESS
        runs = json.loads(listing.stdout)["runs"]
        by_session = {run["session_id"]: run for run in runs}
        assert set(by_session) == {"session-alpha", "session-beta"}
        assert by_session["session-alpha"]["result"] is None
        assert by_session["session-beta"]["result"] is None
        for run in by_session.values():
            shown = _run("runs", "show", run["run_id"], "--json", environment=environment)
            assert shown.returncode == RuntimeCliExitCode.SUCCESS
            assert json.loads(shown.stdout) == run
            events = _run(
                "events",
                "--run",
                run["run_id"],
                "--json",
                environment=environment,
            )
            assert events.returncode == RuntimeCliExitCode.SUCCESS
            assert json.loads(events.stdout)["event_count"] == 4

        stopped_alpha = _run("stop", "--session", "session-alpha", environment=environment)
        assert stopped_alpha.returncode == RuntimeCliExitCode.SUCCESS
        assert alpha.wait(timeout=10) == RuntimeCliExitCode.SUCCESS
        assert not (state / "session-alpha").exists()
        assert beta.poll() is None
        assert (state / "session-beta" / "control.sock").exists()
        beta_status = _run("status", "--session", "session-beta", environment=environment)
        assert beta_status.returncode == RuntimeCliExitCode.SUCCESS
        assert beta_status.stdout.startswith("session=session-beta\nmanager-state=running\n")

        middle = json.loads(
            _run("runs", "list", "--json", environment=environment).stdout
        )["runs"]
        middle_by_session = {run["session_id"]: run for run in middle}
        assert middle_by_session["session-alpha"]["result"] == "completed"
        assert middle_by_session["session-beta"]["result"] is None
        alpha_events = json.loads(
            _run(
                "events",
                "--run",
                middle_by_session["session-alpha"]["run_id"],
                "--json",
                environment=environment,
            ).stdout
        )
        beta_events = json.loads(
            _run(
                "events",
                "--run",
                middle_by_session["session-beta"]["run_id"],
                "--json",
                environment=environment,
            ).stdout
        )
        assert alpha_events["event_count"] == 12
        assert beta_events["event_count"] == 4

        stopped_beta = _run("stop", "--session", "session-beta", environment=environment)
        assert stopped_beta.returncode == RuntimeCliExitCode.SUCCESS
        assert beta.wait(timeout=10) == RuntimeCliExitCode.SUCCESS
        assert not (state / "session-beta").exists()
        completed = json.loads(
            _run("runs", "list", "--json", environment=environment).stdout
        )["runs"]
        assert {run["session_id"] for run in completed} == {
            "session-alpha",
            "session-beta",
        }
        assert all(run["result"] == "completed" for run in completed)
        assert tuple(state.iterdir()) == ()
    finally:
        _stop_test_owner(alpha)
        if beta is not None:
            _stop_test_owner(beta)


@pytest.mark.skipif(sys.platform not in {"darwin", "linux"}, reason="Unix sockets required")
def test_two_sessions_finalize_near_simultaneously(
    short_state_directory: Path,
) -> None:
    state = short_state_directory
    environment = _environment(state)
    history_root = Path(environment["HIYELX_RUNTIME_HISTORY_DIR"])
    bootstrap = open_writer(root=history_root)
    bootstrap.close()
    owners = (
        _start_owner(environment, session="session-alpha"),
        _start_owner(environment, session="session-beta"),
    )
    try:
        assert _read_lines(owners[0], 3)[1:] == ("runtime=running", "control=ready")
        assert _read_lines(owners[1], 3)[1:] == ("runtime=running", "control=ready")
        clients = tuple(
            subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "hiyelx.cli",
                    "runtime",
                    "stop",
                    "--session",
                    session,
                ],
                cwd=_ROOT,
                env=environment,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            for session in ("session-alpha", "session-beta")
        )
        client_results = tuple(client.communicate(timeout=15) for client in clients)
        assert all(client.returncode == RuntimeCliExitCode.SUCCESS for client in clients)
        assert all(stderr == "" for _stdout, stderr in client_results)
        assert all(owner.wait(timeout=10) == RuntimeCliExitCode.SUCCESS for owner in owners)

        runs = json.loads(_run("runs", "list", "--json", environment=environment).stdout)[
            "runs"
        ]
        assert {run["session_id"] for run in runs} == {"session-alpha", "session-beta"}
        assert all(run["result"] == "completed" for run in runs)
        assert tuple(state.iterdir()) == ()
    finally:
        for owner in owners:
            _stop_test_owner(owner)


@pytest.mark.skipif(sys.platform not in {"darwin", "linux"}, reason="Unix sockets required")
def test_foreground_sigint_uses_ordered_cleanup(short_state_directory: Path) -> None:
    state = short_state_directory
    owner = _start_owner(_environment(state), session="interrupt")
    try:
        assert _read_lines(owner, 3) == (
            "session=interrupt",
            "runtime=running",
            "control=ready",
        )
        owner.send_signal(signal.SIGINT)
        assert owner.wait(timeout=10) == RuntimeCliExitCode.SUCCESS
        assert owner.stdout is not None
        assert owner.stdout.read() == "runtime=stopped\n"
        assert owner.stderr is not None
        assert owner.stderr.read() == ""
        assert not (state / "interrupt").exists()
        runs = json.loads(
            _run("runs", "list", "--json", environment=_environment(state)).stdout
        )
        assert runs["run_count"] == 1
        assert runs["runs"][0]["result"] == "interrupted"
        assert runs["runs"][0]["stop_reason"] == "sigint"
        run_id = cast(str, runs["runs"][0]["run_id"])
        events = json.loads(
            _run(
                "events",
                "--run",
                run_id,
                "--json",
                environment=_environment(state),
            ).stdout
        )
        assert events["event_count"] == 12
        assert [event["sequence"] for event in events["events"]] == list(range(12))
        assert events["events"][-1]["event_type"] == "runtime_stopped"
    finally:
        _stop_test_owner(owner)


@pytest.mark.skipif(sys.platform not in {"darwin", "linux"}, reason="Unix required")
def test_forced_owner_exit_preserves_committed_events_and_incomplete_run(
    short_state_directory: Path,
) -> None:
    state = short_state_directory
    environment = _environment(state)
    owner = _start_owner(environment, session="crash-prefix")
    try:
        assert _read_lines(owner, 3) == (
            "session=crash-prefix",
            "runtime=running",
            "control=ready",
        )
        runs = json.loads(
            _run("runs", "list", "--json", environment=environment).stdout
        )["runs"]
        assert len(runs) == 1
        run_id = cast(str, runs[0]["run_id"])
        active_events = json.loads(
            _run(
                "events",
                "--run",
                run_id,
                "--json",
                environment=environment,
            ).stdout
        )
        assert active_events["event_count"] == 4

        owner.kill()
        assert owner.wait(timeout=10) < 0

        incomplete = json.loads(
            _run("runs", "show", run_id, "--json", environment=environment).stdout
        )
        assert incomplete["ended_at"] is None
        assert incomplete["result"] is None
        assert incomplete["stop_reason"] is None
        assert incomplete["event_high_water_mark"] == 3
        committed = json.loads(
            _run(
                "events",
                "--run",
                run_id,
                "--json",
                environment=environment,
            ).stdout
        )
        assert committed == active_events
    finally:
        _stop_test_owner(owner)


@pytest.mark.skipif(sys.platform not in {"darwin", "linux"}, reason="Unix sockets required")
def test_two_connected_stop_clients_share_one_cleanup_transition(
    short_state_directory: Path,
) -> None:
    state = short_state_directory
    owner = _start_owner(_environment(state), session="concurrent")
    clients = (socket.socket(socket.AF_UNIX), socket.socket(socket.AF_UNIX))
    try:
        assert _read_lines(owner, 3) == (
            "session=concurrent",
            "runtime=running",
            "control=ready",
        )
        socket_path = state / "concurrent" / "control.sock"
        for client in clients:
            client.settimeout(5)
            client.connect(str(socket_path))
        request = (
            b'{"command":"stop","protocol_version":1,'
            b'"session":"concurrent"}\n'
        )
        for client in clients:
            client.sendall(request)

        replies = tuple(_receive_raw_reply(client) for client in clients)
        assert replies == (
            {
                "kind": "stop",
                "ok": True,
                "protocol_version": 1,
                "result": {"session": "concurrent", "stopped": True},
            },
        ) * 2
        assert owner.wait(timeout=10) == RuntimeCliExitCode.SUCCESS
        assert owner.stdout is not None
        assert owner.stdout.read() == "runtime=stopped\n"
        assert owner.stderr is not None
        assert owner.stderr.read() == ""
        assert not (state / "concurrent").exists()
        runs = json.loads(
            _run("runs", "list", "--json", environment=_environment(state)).stdout
        )
        assert runs["run_count"] == 1
        assert runs["runs"][0]["result"] == "completed"
        events = json.loads(
            _run(
                "events",
                "--run",
                runs["runs"][0]["run_id"],
                "--json",
                environment=_environment(state),
            ).stdout
        )
        assert events["event_count"] == 12
        assert [event["sequence"] for event in events["events"]] == list(range(12))
    finally:
        for client in clients:
            client.close()
        _stop_test_owner(owner)


@pytest.mark.skipif(sys.platform not in {"darwin", "linux"}, reason="Unix sockets required")
def test_runtime_startup_failure_is_sanitized_and_removes_artifacts(
    tmp_path: Path,
    short_state_directory: Path,
) -> None:
    state = short_state_directory
    config = tmp_path / "private-config.yaml"
    config.write_text(
        """\
schema_version: "1"
resources:
  - identity: sim_motor
    model: motor.simulated
    settings:
      credential: top-secret
      device: /dev/private
""",
        encoding="utf-8",
    )
    result = _run(
        "start",
        str(config),
        "--session",
        "failure",
        environment=_environment(state),
    )

    assert result.returncode == RuntimeCliExitCode.RUNTIME_STARTUP_FAILURE
    assert result.stdout == ""
    assert result.stderr == "error: runtime startup failed\n"
    assert "top-secret" not in result.stderr
    assert "/dev/private" not in result.stderr
    assert str(config) not in result.stderr
    assert not (state / "failure").exists()
    runs = json.loads(
        _run("runs", "list", "--json", environment=_environment(state)).stdout
    )
    assert runs["run_count"] == 1
    assert runs["runs"][0]["result"] == "startup_failed"
    assert runs["runs"][0]["stop_reason"] == "startup_failure"


def test_invalid_configuration_creates_no_run(
    tmp_path: Path,
    short_state_directory: Path,
) -> None:
    config = tmp_path / "invalid.yaml"
    config.write_text("credential: top-secret\n", encoding="utf-8")
    environment = _environment(short_state_directory)

    result = _run(
        "start",
        str(config),
        "--session",
        "invalid",
        environment=environment,
    )

    assert result.returncode == RuntimeCliExitCode.INVALID_CONFIGURATION
    assert result.stdout == ""
    assert result.stderr == "error: runtime configuration is invalid\n"
    history_root = Path(environment["HIYELX_RUNTIME_HISTORY_DIR"])
    assert not history_root.exists()
    assert not (short_state_directory / "invalid").exists()


@pytest.mark.parametrize("line_count", (1, 2))
def test_readiness_test_helper_bounds_the_complete_protocol(line_count: int) -> None:
    payload = repr("\n".join(_READY_LINES[:line_count]) + "\n")
    owner = subprocess.Popen(
        [
            sys.executable,
            "-c",
            f"import sys,time; sys.stdout.write({payload}); sys.stdout.flush(); "
            "time.sleep(30)",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    started = time.monotonic()
    try:
        with pytest.raises(AssertionError, match="did not become ready"):
            _read_lines(owner, 3, timeout_seconds=0.2)
        assert time.monotonic() - started < 2.0
    finally:
        owner.terminate()
        owner.wait(timeout=5)
    assert owner.poll() is not None


def _environment(state: Path) -> dict[str, str]:
    environment = os.environ.copy()
    environment["HIYELX_RUNTIME_STATE_DIR"] = str(state)
    environment["HIYELX_RUNTIME_HISTORY_DIR"] = str(
        state.parent / f"{state.name}-history"
    )
    return environment


def _start_owner(
    environment: dict[str, str],
    *,
    session: str = "alpha",
) -> subprocess.Popen[str]:
    return subprocess.Popen(
        [
            sys.executable,
            "-m",
            "hiyelx.cli",
            "runtime",
            "start",
            str(_CONFIG),
            "--session",
            session,
        ],
        cwd=_ROOT,
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


def _run(
    *arguments: str,
    environment: dict[str, str],
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "hiyelx.cli", "runtime", *arguments],
        cwd=_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )


def _read_lines(
    process: subprocess.Popen[str],
    count: int,
    *,
    timeout_seconds: float = 10.0,
) -> tuple[str, ...]:
    assert process.stdout is not None
    deadline = time.monotonic() + timeout_seconds
    pending = bytearray()
    lines: list[str] = []
    while len(lines) < count:
        while b"\n" in pending and len(lines) < count:
            line, _, remainder = pending.partition(b"\n")
            pending = bytearray(remainder)
            lines.append(bytes(line).decode("utf-8"))
        if len(lines) == count:
            break
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise AssertionError("runtime owner did not become ready")
        readable, _, _ = select.select([process.stdout], [], [], remaining)
        if not readable:
            raise AssertionError("runtime owner did not become ready")
        chunk = os.read(process.stdout.fileno(), 4096)
        if not chunk:
            assert process.stderr is not None
            stderr = process.stderr.read() if process.poll() is not None else ""
            raise AssertionError(stderr)
        pending.extend(chunk)
    return tuple(lines)


def _receive_raw_reply(connection: socket.socket) -> dict[str, object]:
    response = b""
    while not response.endswith(b"\n"):
        chunk = connection.recv(MAX_MESSAGE_BYTES + 1)
        if not chunk:
            break
        response += chunk
    decoded = cast(object, json.loads(response.decode("utf-8")))
    assert isinstance(decoded, dict)
    return cast(dict[str, object], decoded)


def _assert_protocol_rejections_do_not_stop_owner(
    state: Path,
    owner: subprocess.Popen[str],
) -> None:
    socket_path = state / "alpha" / "control.sock"
    unknown = json.dumps(
        {"command": "unknown", "protocol_version": 1, "session": "alpha"},
        separators=(",", ":"),
        sort_keys=True,
    ).encode("ascii") + b"\n"
    malformed = b'{"command":\n'
    oversized = b"x" * (MAX_MESSAGE_BYTES + 1) + b"\n"

    assert _raw_request(socket_path, unknown) == {
        "error": {
            "code": "unknown_command",
            "message": "control command is unknown",
        },
        "ok": False,
        "protocol_version": 1,
    }
    assert _error_code(_raw_request(socket_path, malformed)) == "invalid_request"
    assert _error_code(_raw_request(socket_path, oversized)) == "invalid_request"

    disconnected = socket.socket(socket.AF_UNIX)
    disconnected.connect(str(socket_path))
    disconnected.close()
    assert owner.poll() is None


def _raw_request(socket_path: Path, message: bytes) -> dict[str, object]:
    connection = socket.socket(socket.AF_UNIX)
    connection.settimeout(5)
    try:
        connection.connect(str(socket_path))
        connection.sendall(message)
        return _receive_raw_reply(connection)
    finally:
        connection.close()


def _error_code(response: dict[str, object]) -> object:
    error = response["error"]
    assert isinstance(error, dict)
    typed_error = cast(dict[str, object], error)
    return typed_error["code"]


def _stop_test_owner(owner: subprocess.Popen[str]) -> None:
    if owner.poll() is None:
        owner.terminate()
        owner.wait(timeout=10)


@pytest.fixture
def short_state_directory() -> Iterator[Path]:
    with tempfile.TemporaryDirectory(prefix="hiyelx-rto2-") as path:
        state = Path(path)
        try:
            yield state
        finally:
            history_root = state.parent / f"{state.name}-history"
            if history_root.exists():
                shutil.rmtree(history_root)
