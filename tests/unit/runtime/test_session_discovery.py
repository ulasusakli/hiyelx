import asyncio
import json
import os
import selectors
import socket
import stat
import subprocess
import sys
import tempfile
import threading
import time
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from hiyelx import cli
from hiyelx.config import ResourceDefinition, RuntimeConfig
from hiyelx.resources import ResourceIdentity
from hiyelx.runtime import control
from hiyelx.runtime.control import (
    MAX_OBSERVABLE_SESSIONS,
    MAX_SESSION_DISCOVERY_ENTRIES,
    PROTOCOL_VERSION,
    STATE_DIRECTORY_ENV,
    RuntimeCliExitCode,
    SessionNotRunningError,
    UnsafeSessionPathError,
    configuration_fingerprint,
    list_observable_sessions,
    request_preview,
    request_status,
    request_stop,
    reserve_session,
)
from hiyelx.studio.application import (
    StudioApplicationError,
    StudioErrorCode,
    get_preview,
)

_LOCK_HELPER_STARTUP_TIMEOUT_SECONDS = 15.0
_LOCK_HELPER_CLEANUP_TIMEOUT_SECONDS = 3.0
_LOCK_HELPER_DIAGNOSTIC_LIMIT = 2_000

_LOCK_PROCESS_SCRIPT = r"""
import fcntl
import os
import socket
import sys
from pathlib import Path

mode = sys.argv[1]
if mode == "owner":
    print("progress:bootstrap", flush=True)
    from hiyelx.runtime.control import reserve_session

    print("progress:control-imported", flush=True)
    state = Path(sys.argv[2])
    session = sys.argv[3]
    owned = reserve_session(session, state_directory=state)
    print("progress:session-reserved", flush=True)
    listener = None
    try:
        listener = socket.socket(socket.AF_UNIX)
        listener.bind(str(owned.layout.socket))
        os.chmod(owned.layout.socket, 0o600, follow_symlinks=False)
        print("progress:socket-bound", flush=True)
        owned.publish("0" * 64)
        print("progress:session-published", flush=True)
        print("locked", flush=True)
        sys.stdin.readline()
    finally:
        if listener is not None:
            listener.close()
        if not owned.cleanup(final=True):
            raise SystemExit(3)
    raise SystemExit(0)

lock = Path(sys.argv[2])
descriptor = os.open(lock, os.O_RDWR)
try:
    if mode == "hold":
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        print("locked", flush=True)
        sys.stdin.readline()
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        raise SystemExit(0)
    if mode == "try":
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print("blocked", flush=True)
            raise SystemExit(2)
        print("acquired", flush=True)
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        raise SystemExit(0)
    raise SystemExit(4)
finally:
    os.close(descriptor)
"""


def test_missing_and_empty_state_roots_return_empty_without_creation(
    tmp_path: Path,
) -> None:
    missing = tmp_path / "missing"

    assert list_observable_sessions(state_directory=missing) == ()
    assert not missing.exists()

    empty = tmp_path / "empty"
    empty.mkdir(mode=0o700)
    before = _tree_snapshot(empty)

    assert list_observable_sessions(state_directory=empty) == ()
    assert _tree_snapshot(empty) == before


def test_active_sessions_are_validated_sorted_and_read_only(
    discovery_state_directory: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owned_sessions = [
        _active_session(discovery_state_directory, session)
        for session in ("zeta", "alpha", "middle")
    ]

    def forbidden(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("discovery called a mutating session helper")

    before = _tree_snapshot(discovery_state_directory)
    try:
        with monkeypatch.context() as discovery_guard:
            discovery_guard.setattr(control, "reserve_session", forbidden)
            discovery_guard.setattr(control, "_locate_active_session", forbidden)
            discovery_guard.setattr(control, "_clear_stale_control_artifacts", forbidden)
            discovery_guard.setattr(control, "_unlink_owned", forbidden)
            assert list_observable_sessions(
                state_directory=discovery_state_directory
            ) == ("alpha", "middle", "zeta")
        assert _tree_snapshot(discovery_state_directory) == before
    finally:
        for owned, bound_socket in reversed(owned_sessions):
            bound_socket.close()
            assert owned.cleanup(final=True)


def test_valid_stale_session_is_omitted_without_cleanup(
    discovery_state_directory: Path,
) -> None:
    stale = _stale_session(discovery_state_directory, "stale")
    before = _tree_snapshot(discovery_state_directory)

    assert list_observable_sessions(state_directory=discovery_state_directory) == ()
    assert _tree_snapshot(discovery_state_directory) == before
    assert stale.exists()


def test_independent_runtime_owner_keeps_exclusive_lock_during_discovery(
    discovery_state_directory: Path,
) -> None:
    owner = _start_lock_process(
        "owner",
        discovery_state_directory,
        "owned",
    )
    try:
        session = discovery_state_directory / "owned"
        before = _tree_snapshot(discovery_state_directory)

        assert list_observable_sessions(
            state_directory=discovery_state_directory
        ) == ("owned",)
        assert not _independent_process_can_lock(session / "owner.lock")
        assert _tree_snapshot(discovery_state_directory) == before
    finally:
        _stop_lock_process(owner)

    assert not (discovery_state_directory / "owned").exists()


def test_lock_helper_early_exit_is_diagnostic_and_releases_descriptors(
    discovery_state_directory: Path,
) -> None:
    lock = discovery_state_directory / "diagnostic.lock"
    lock.write_bytes(b"")
    lock.chmod(0o600)

    with pytest.raises(AssertionError, match="exited before readiness.*returncode=4"):
        _start_lock_process("invalid", lock)

    assert _independent_process_can_lock(lock)


def test_stale_lock_probe_releases_before_return_and_between_repeated_calls(
    discovery_state_directory: Path,
) -> None:
    stale = _stale_session(discovery_state_directory, "stale-lock")
    before = _tree_snapshot(discovery_state_directory)

    for _index in range(3):
        assert list_observable_sessions(
            state_directory=discovery_state_directory
        ) == ()
        assert _independent_process_can_lock(stale / "owner.lock")

    assert _tree_snapshot(discovery_state_directory) == before


def test_probe_exception_releases_transient_lock_for_independent_process(
    discovery_state_directory: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stale = _stale_session(discovery_state_directory, "probe-error")
    before = _tree_snapshot(discovery_state_directory)
    real_fcntl = control._fcntl()  # pyright: ignore[reportPrivateUsage]

    class FailingUnlock:
        LOCK_EX = real_fcntl.LOCK_EX
        LOCK_NB = real_fcntl.LOCK_NB
        LOCK_UN = real_fcntl.LOCK_UN

        @staticmethod
        def flock(file_descriptor: int, operation: int) -> None:
            if operation == real_fcntl.LOCK_UN:
                raise OSError("injected unlock failure")
            real_fcntl.flock(file_descriptor, operation)

    monkeypatch.setattr(control, "_fcntl", lambda: FailingUnlock())

    with pytest.raises(UnsafeSessionPathError):
        list_observable_sessions(state_directory=discovery_state_directory)

    assert _independent_process_can_lock(stale / "owner.lock")
    assert _tree_snapshot(discovery_state_directory) == before


@pytest.mark.parametrize("transition", ("startup", "shutdown"))
def test_cross_process_lock_transition_during_probe_fails_closed(
    transition: str,
    discovery_state_directory: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stale = _stale_session(discovery_state_directory, f"race-{transition}")
    before = _tree_snapshot(discovery_state_directory)
    entered_manifest_read = threading.Event()
    continue_manifest_read = threading.Event()
    original_read_manifest = control._read_manifest  # pyright: ignore[reportPrivateUsage]
    holder: subprocess.Popen[str] | None = None

    def blocked_manifest_read(layout: control.SessionLayout) -> control.SessionManifest:
        entered_manifest_read.set()
        assert continue_manifest_read.wait(timeout=2)
        return original_read_manifest(layout)

    monkeypatch.setattr(control, "_read_manifest", blocked_manifest_read)
    if transition == "shutdown":
        holder = _start_lock_process("hold", stale / "owner.lock")

    try:
        with ThreadPoolExecutor(max_workers=1) as executor:
            result = executor.submit(
                list_observable_sessions,
                state_directory=discovery_state_directory,
            )
            assert entered_manifest_read.wait(timeout=2)
            if transition == "startup":
                holder = _start_lock_process("hold", stale / "owner.lock")
            else:
                assert holder is not None
                _stop_lock_process(holder)
                holder = None
            continue_manifest_read.set()
            with pytest.raises(UnsafeSessionPathError):
                result.result(timeout=2)
    finally:
        continue_manifest_read.set()
        if holder is not None:
            _stop_lock_process(holder)

    assert _independent_process_can_lock(stale / "owner.lock")
    assert _tree_snapshot(discovery_state_directory) == before


@pytest.mark.parametrize("unsafe", ("mode", "session-symlink", "root-symlink"))
def test_unsafe_modes_and_symlinks_fail_closed_without_mutation(
    unsafe: str,
    tmp_path: Path,
) -> None:
    target = tmp_path / "target"
    target.mkdir(mode=0o700)
    state = tmp_path / "state"
    if unsafe == "root-symlink":
        state.symlink_to(target, target_is_directory=True)
    else:
        state.mkdir(mode=0o700)
        if unsafe == "session-symlink":
            (state / "alpha").symlink_to(target, target_is_directory=True)
        else:
            session = state / "alpha"
            session.mkdir(mode=0o755)
            (session / "owner.lock").write_bytes(b"")
            (session / "owner.lock").chmod(0o600)
    before = _tree_snapshot(tmp_path)

    with pytest.raises(UnsafeSessionPathError):
        list_observable_sessions(state_directory=state)

    assert _tree_snapshot(tmp_path) == before


def test_foreign_owned_session_fails_closed_without_mutation(
    discovery_state_directory: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stale_session(discovery_state_directory, "alpha")
    target = discovery_state_directory / "alpha"
    before = _tree_snapshot(discovery_state_directory)
    original_lstat = control.os.lstat

    def foreign_lstat(path: os.PathLike[str] | str) -> os.stat_result:
        result = original_lstat(path)
        if Path(path) == target:
            values = list(result)
            values[4] = result.st_uid + 1
            return os.stat_result(values)
        return result

    monkeypatch.setattr(control.os, "lstat", foreign_lstat)

    with pytest.raises(UnsafeSessionPathError):
        list_observable_sessions(state_directory=discovery_state_directory)

    assert _tree_snapshot(discovery_state_directory) == before


@pytest.mark.parametrize(
    "failure",
    (
        "malformed-manifest",
        "duplicate-manifest",
        "boolean-version",
        "invalid-session",
    ),
)
def test_malformed_metadata_and_invalid_session_ids_fail_closed_without_mutation(
    failure: str,
    discovery_state_directory: Path,
) -> None:
    if failure == "malformed-manifest":
        session = _stale_session(discovery_state_directory, "alpha")
        (session / "manifest.json").write_text("private-path=/tmp/secret")
        (session / "manifest.json").chmod(0o600)
    elif failure == "duplicate-manifest":
        session = _stale_session(discovery_state_directory, "alpha")
        (session / "manifest.json").write_text(
            '{"config_fingerprint":"' + "0" * 64 + '","owner_uid":'
            f'{os.geteuid()},"pid":{os.getpid()},"protocol_version":1,'
            '"session":"alpha","session":"alpha"}'
        )
    elif failure == "boolean-version":
        session = _stale_session(discovery_state_directory, "alpha")
        document = json.loads((session / "manifest.json").read_text())
        document["protocol_version"] = True
        (session / "manifest.json").write_text(json.dumps(document))
    else:
        session = discovery_state_directory / "Invalid"
        session.mkdir(mode=0o700)
        (session / "owner.lock").write_bytes(b"")
        (session / "owner.lock").chmod(0o600)
    before = _tree_snapshot(discovery_state_directory)

    with pytest.raises(UnsafeSessionPathError) as caught:
        list_observable_sessions(state_directory=discovery_state_directory)

    assert str(caught.value) == ""
    assert "secret" not in repr(caught.value)
    assert _tree_snapshot(discovery_state_directory) == before


def test_state_root_scan_limit_fails_closed_without_mutation(
    discovery_state_directory: Path,
) -> None:
    for index in range(MAX_SESSION_DISCOVERY_ENTRIES + 1):
        (discovery_state_directory / f"s{index:03d}").mkdir(mode=0o700)
    before = _tree_snapshot(discovery_state_directory)

    with pytest.raises(UnsafeSessionPathError):
        list_observable_sessions(state_directory=discovery_state_directory)

    assert _tree_snapshot(discovery_state_directory) == before


def test_observable_session_limit_fails_closed_without_mutation(
    discovery_state_directory: Path,
) -> None:
    owned_sessions = [
        _active_session(discovery_state_directory, f"s{index:02d}")
        for index in range(MAX_OBSERVABLE_SESSIONS + 1)
    ]
    before = _tree_snapshot(discovery_state_directory)
    try:
        with pytest.raises(UnsafeSessionPathError):
            list_observable_sessions(state_directory=discovery_state_directory)
        assert _tree_snapshot(discovery_state_directory) == before
    finally:
        for owned, bound_socket in reversed(owned_sessions):
            bound_socket.close()
            assert owned.cleanup(final=True)


def test_concurrent_owner_shutdown_fails_closed_without_discovery_cleanup(
    discovery_state_directory: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owned, bound_socket = _active_session(discovery_state_directory, "closing")
    entered_manifest_read = threading.Event()
    continue_manifest_read = threading.Event()
    original_read_manifest = control._read_manifest  # pyright: ignore[reportPrivateUsage]

    def blocked_manifest_read(layout: control.SessionLayout) -> control.SessionManifest:
        entered_manifest_read.set()
        assert continue_manifest_read.wait(timeout=2)
        return original_read_manifest(layout)

    monkeypatch.setattr(control, "_read_manifest", blocked_manifest_read)
    with ThreadPoolExecutor(max_workers=1) as executor:
        result = executor.submit(
            list_observable_sessions,
            state_directory=discovery_state_directory,
        )
        assert entered_manifest_read.wait(timeout=2)
        bound_socket.close()
        assert owned.cleanup(final=True)
        continue_manifest_read.set()
        with pytest.raises(UnsafeSessionPathError):
            result.result(timeout=2)

    assert not (discovery_state_directory / "closing").exists()


@pytest.mark.asyncio
async def test_stale_preview_and_studio_preview_fail_without_artifact_mutation(
    discovery_state_directory: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stale = _stale_session(discovery_state_directory, "stale-preview")
    before = _tree_snapshot(discovery_state_directory)

    def forbidden(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("preview attempted runtime artifact cleanup")

    with monkeypatch.context() as read_only_guard:
        read_only_guard.setattr(control.OwnedSession, "cleanup", forbidden)
        read_only_guard.setattr(control, "_unlink_owned", forbidden)
        with pytest.raises(SessionNotRunningError):
            await request_preview(
                "stale-preview",
                state_directory=discovery_state_directory,
            )
        with pytest.raises(StudioApplicationError) as caught:
            await get_preview(
                "stale-preview",
                state_directory=discovery_state_directory,
            )

    assert caught.value.code is StudioErrorCode.SESSION_NOT_RUNNING
    assert str(caught.value) == "The selected session is not running."
    assert _independent_process_can_lock(stale / "owner.lock")
    assert _tree_snapshot(discovery_state_directory) == before
    assert stale.exists()


def test_cli_stale_preview_keeps_exact_failure_and_artifacts(
    discovery_state_directory: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    stale = _stale_session(discovery_state_directory, "stale-cli")
    before = _tree_snapshot(discovery_state_directory)
    monkeypatch.setenv(STATE_DIRECTORY_ENV, str(discovery_state_directory))

    result = cli.main(["runtime", "preview", "--session", "stale-cli"])

    captured = capsys.readouterr()
    assert result == RuntimeCliExitCode.SESSION_NOT_RUNNING
    assert captured.out == ""
    assert captured.err == "error: runtime session is not running\n"
    assert _tree_snapshot(discovery_state_directory) == before
    assert stale.exists()


@pytest.mark.parametrize("command", ("status", "stop"))
@pytest.mark.asyncio
async def test_status_and_stop_retain_stale_session_cleanup(
    command: str,
    discovery_state_directory: Path,
) -> None:
    session = f"stale-{command}"
    stale = _stale_session(discovery_state_directory, session)

    with pytest.raises(SessionNotRunningError):
        if command == "status":
            await request_status(session, state_directory=discovery_state_directory)
        else:
            await request_stop(session, state_directory=discovery_state_directory)

    assert not stale.exists()


def test_concurrent_shutdown_and_preview_fail_closed_without_preview_cleanup(
    discovery_state_directory: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owned, bound_socket = _active_session(discovery_state_directory, "preview-race")
    entered_manifest_read = threading.Event()
    continue_manifest_read = threading.Event()
    original_read_manifest = control._read_manifest  # pyright: ignore[reportPrivateUsage]
    original_cleanup = control.OwnedSession.cleanup
    cleanup_owners: list[bool] = []

    def blocked_manifest_read(layout: control.SessionLayout) -> control.SessionManifest:
        entered_manifest_read.set()
        assert continue_manifest_read.wait(timeout=2)
        return original_read_manifest(layout)

    def tracked_cleanup(
        session: control.OwnedSession,
        *,
        final: bool = False,
    ) -> bool:
        cleanup_owners.append(session is owned)
        return original_cleanup(session, final=final)

    monkeypatch.setattr(control, "_read_manifest", blocked_manifest_read)
    monkeypatch.setattr(control.OwnedSession, "cleanup", tracked_cleanup)

    def preview() -> control.PreviewReply:
        return asyncio.run(
            request_preview(
                "preview-race",
                state_directory=discovery_state_directory,
            )
        )

    with ThreadPoolExecutor(max_workers=1) as executor:
        result = executor.submit(preview)
        assert entered_manifest_read.wait(timeout=2)
        try:
            bound_socket.close()
            assert owned.cleanup(final=True)
        finally:
            continue_manifest_read.set()
        with pytest.raises(UnsafeSessionPathError):
            result.result(timeout=2)

    assert cleanup_owners == [True]
    assert not (discovery_state_directory / "preview-race").exists()


def _active_session(
    state: Path,
    session: str,
) -> tuple[control.OwnedSession, socket.socket]:
    owned = reserve_session(session, state_directory=state)
    bound_socket = socket.socket(socket.AF_UNIX)
    bound_socket.bind(str(owned.layout.socket))
    owned.layout.socket.chmod(0o600)
    owned.publish(configuration_fingerprint(_simulation_config()))
    return owned, bound_socket


def _simulation_config() -> RuntimeConfig:
    return RuntimeConfig(
        schema_version="1",
        resources=[
            ResourceDefinition(
                identity=ResourceIdentity("sim_motor"),
                model="motor.simulated",
                settings={},
            )
        ],
    )


def _stale_session(state: Path, session: str) -> Path:
    directory = state / session
    directory.mkdir(mode=0o700)
    lock = directory / "owner.lock"
    lock.write_bytes(b"")
    lock.chmod(0o600)
    manifest = directory / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "config_fingerprint": "0" * 64,
                "owner_uid": os.geteuid(),
                "pid": os.getpid(),
                "protocol_version": PROTOCOL_VERSION,
                "session": session,
            },
            separators=(",", ":"),
            sort_keys=True,
        )
    )
    manifest.chmod(0o600)
    bound_socket = socket.socket(socket.AF_UNIX)
    try:
        bound_socket.bind(str(directory / "control.sock"))
    finally:
        bound_socket.close()
    (directory / "control.sock").chmod(0o600)
    return directory


def _tree_snapshot(
    root: Path,
) -> dict[str, tuple[int, int, int, int, int, bytes | str]]:
    if not root.exists() and not root.is_symlink():
        return {}
    paths = [root]
    if root.is_dir() and not root.is_symlink():
        paths.extend(sorted(root.rglob("*")))
    snapshot: dict[str, tuple[int, int, int, int, int, bytes | str]] = {}
    for path in paths:
        result = path.lstat()
        payload: bytes | str = b""
        if stat.S_ISREG(result.st_mode):
            payload = path.read_bytes()
        elif stat.S_ISLNK(result.st_mode):
            payload = os.readlink(path)
        snapshot[str(path.relative_to(root.parent))] = (
            result.st_ino,
            result.st_mode,
            result.st_size,
            result.st_mtime_ns,
            result.st_ctime_ns,
            payload,
        )
    return snapshot


def _start_lock_process(
    mode: str,
    *arguments: Path | str,
) -> subprocess.Popen[str]:
    process = subprocess.Popen(
        [
            sys.executable,
            "-c",
            _LOCK_PROCESS_SCRIPT,
            mode,
            *(str(argument) for argument in arguments),
        ],
        cwd=Path(__file__).resolve().parents[3],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        failure, observed_stdout, observed_stderr = _wait_for_lock_helper_ready(
            process
        )
    except BaseException:
        _terminate_lock_process(process)
        raise
    if failure is not None:
        remaining_stdout, remaining_stderr = _terminate_lock_process(process)
        raise AssertionError(
            f"lock helper {failure}; "
            + _lock_helper_diagnostics(
                process,
                observed_stdout + remaining_stdout,
                observed_stderr + remaining_stderr,
            )
        )
    return process


def _wait_for_lock_helper_ready(
    process: subprocess.Popen[str],
) -> tuple[str | None, str, str]:
    assert process.stdout is not None
    assert process.stderr is not None
    observed_stdout: list[str] = []
    observed_stderr: list[str] = []
    pending_stdout: bytes = b""
    deadline = time.monotonic() + _LOCK_HELPER_STARTUP_TIMEOUT_SECONDS
    selector = selectors.DefaultSelector()
    selector.register(process.stdout, selectors.EVENT_READ, "stdout")
    selector.register(process.stderr, selectors.EVENT_READ, "stderr")
    try:
        while True:
            returncode = process.poll()
            if returncode is not None:
                return (
                    f"exited before readiness with returncode={returncode}",
                    "".join(observed_stdout),
                    "".join(observed_stderr),
                )
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                progress = [
                    line.rstrip("\n")
                    for line in observed_stdout
                    if line.startswith("progress:")
                ]
                return (
                    "readiness timed out after "
                    f"{_LOCK_HELPER_STARTUP_TIMEOUT_SECONDS:g}s while still running; "
                    f"last_progress={progress[-1] if progress else 'none'}",
                    "".join(observed_stdout),
                    "".join(observed_stderr),
                )
            events = selector.select(remaining)
            if not events:
                continue
            for key, _mask in events:
                if key.data == "stdout":
                    stdout_chunk: bytes = os.read(process.stdout.fileno(), 4_096)
                    if stdout_chunk == b"":
                        try:
                            returncode = process.wait(
                                timeout=_LOCK_HELPER_CLEANUP_TIMEOUT_SECONDS
                            )
                        except subprocess.TimeoutExpired:
                            return (
                                "closed stdout before readiness while still running",
                                "".join(observed_stdout)
                                + pending_stdout.decode("utf-8", errors="replace"),
                                "".join(observed_stderr),
                            )
                        return (
                            f"exited before readiness with returncode={returncode}",
                            "".join(observed_stdout)
                            + pending_stdout.decode("utf-8", errors="replace"),
                            "".join(observed_stderr),
                        )
                    pending_stdout = pending_stdout + stdout_chunk
                    newline_index = pending_stdout.find(b"\n")
                    while newline_index >= 0:
                        raw_line: bytes = pending_stdout[:newline_index]
                        pending_stdout = pending_stdout[newline_index + 1 :]
                        line = raw_line.decode("utf-8", errors="replace") + "\n"
                        observed_stdout.append(line)
                        if line == "locked\n":
                            return (
                                None,
                                "".join(observed_stdout),
                                "".join(observed_stderr),
                            )
                        if not line.startswith("progress:"):
                            return (
                                f"sent unexpected readiness output {line.rstrip()!r}",
                                "".join(observed_stdout),
                                "".join(observed_stderr),
                            )
                        newline_index = pending_stdout.find(b"\n")
                else:
                    stderr_chunk: bytes = os.read(process.stderr.fileno(), 4_096)
                    if stderr_chunk == b"":
                        selector.unregister(process.stderr)
                    else:
                        observed_stderr.append(
                            stderr_chunk.decode("utf-8", errors="replace")
                        )
    finally:
        selector.close()


def _terminate_lock_process(process: subprocess.Popen[str]) -> tuple[str, str]:
    if process.poll() is None:
        process.kill()
    try:
        return process.communicate(timeout=_LOCK_HELPER_CLEANUP_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired:
        process.kill()
        return process.communicate(timeout=_LOCK_HELPER_CLEANUP_TIMEOUT_SECONDS)


def _lock_helper_diagnostics(
    process: subprocess.Popen[str],
    stdout: str,
    stderr: str,
) -> str:
    return (
        f"returncode={process.returncode!r}, "
        f"stdout={_bounded_lock_helper_output(stdout)!r}, "
        f"stderr={_bounded_lock_helper_output(stderr)!r}"
    )


def _bounded_lock_helper_output(output: str) -> str:
    if len(output) <= _LOCK_HELPER_DIAGNOSTIC_LIMIT:
        return output
    return output[:_LOCK_HELPER_DIAGNOSTIC_LIMIT] + "<truncated>"


def _stop_lock_process(process: subprocess.Popen[str]) -> None:
    if process.poll() is not None:
        stdout, stderr = process.communicate(
            timeout=_LOCK_HELPER_CLEANUP_TIMEOUT_SECONDS
        )
        raise AssertionError(
            "lock helper exited before release; "
            + _lock_helper_diagnostics(process, stdout, stderr)
        )
    try:
        stdout, stderr = process.communicate(
            input="\n",
            timeout=_LOCK_HELPER_CLEANUP_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        stdout, stderr = _terminate_lock_process(process)
        raise AssertionError(
            "lock helper release timed out; "
            + _lock_helper_diagnostics(process, stdout, stderr)
        ) from None
    if process.returncode != 0 or stdout != "" or stderr != "":
        raise AssertionError(
            "lock helper release failed; "
            + _lock_helper_diagnostics(process, stdout, stderr)
        )


def _independent_process_can_lock(lock: Path) -> bool:
    try:
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                _LOCK_PROCESS_SCRIPT,
                "try",
                str(lock),
            ],
            cwd=Path(__file__).resolve().parents[3],
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
        )
    except subprocess.TimeoutExpired:
        raise AssertionError("independent lock check timed out") from None
    assert result.stderr == ""
    if result.returncode == 0:
        assert result.stdout == "acquired\n"
        return True
    assert result.returncode == 2
    assert result.stdout == "blocked\n"
    return False


@pytest.fixture
def discovery_state_directory() -> Iterator[Path]:
    with tempfile.TemporaryDirectory(prefix="hsp2-") as path:
        state = Path(path)
        state.chmod(0o700)
        yield state
