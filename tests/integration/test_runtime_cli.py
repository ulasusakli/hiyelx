import json
import os
import select
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
    finally:
        _stop_test_owner(owner)

    for command in ("status", "stop"):
        missing = _run(command, "--session", "alpha", environment=environment)
        assert missing.returncode == RuntimeCliExitCode.SESSION_NOT_RUNNING
        assert missing.stdout == ""
        assert missing.stderr == "error: runtime session is not running\n"


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
    with tempfile.TemporaryDirectory(prefix="hiyelx-rto2-", dir="/private/tmp") as path:
        yield Path(path)
