import ast
import fcntl
import inspect
import os
import sqlite3
import stat
import subprocess
import sys
import textwrap
import time
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast

import pytest

import hiyelx.runtime.events as runtime_events
import hiyelx.runtime.history as history
from hiyelx.resources import HealthStatus, LifecycleState, ResourceIdentity
from hiyelx.runtime import RuntimeEvent, RuntimeEventOperation, RuntimeEventOutcome
from hiyelx.runtime.history import (
    DEFAULT_EVENT_LIMIT,
    HISTORY_DIRECTORY_ENV,
    EventRecord,
    HistoryStoreError,
    InvalidEventCursorError,
    InvalidEventLimitError,
    InvalidHistoryLimitError,
    InvalidRetentionKeepError,
    InvalidRunIdError,
    RunAlreadyFinalizedError,
    RunNotFoundError,
    RunResult,
    StopReason,
    UnsafeHistoryPathError,
    get_run,
    list_events,
    list_runs,
    open_read_only,
    open_writer,
    prune_runs,
    resolve_history_root,
    validate_retention_keep,
)
from hiyelx.runtime.manager import RuntimeManager

_RUN_A = "11111111-1111-4111-8111-111111111111"
_RUN_B = "22222222-2222-4222-8222-222222222222"
_RUN_C = "33333333-3333-4333-8333-333333333333"
_RUN_D = "44444444-4444-4444-8444-444444444444"
_RUN_E = "55555555-5555-4555-8555-555555555555"
_START = datetime(2026, 10, 18, 10, 11, 12, 123456, tzinfo=UTC)
_FINGERPRINT = "a" * 64
_CHILD_DIAGNOSTIC_OUTPUT_LIMIT = 1024


def _format_child_process_diagnostics(
    results: tuple[tuple[int | None, str, str], ...],
    *,
    task_root: Path,
) -> str:
    """Format bounded, ordered child results while redacting local paths."""
    redactions = tuple(
        path
        for path in (str(task_root), str(Path.home()))
        if path and path != "/"
    )

    def bounded_repr(output: str) -> str:
        sanitized = output
        for path in redactions:
            sanitized = sanitized.replace(path, "<redacted-path>")
        if len(sanitized) > _CHILD_DIAGNOSTIC_OUTPUT_LIMIT:
            sanitized = (
                sanitized[:_CHILD_DIAGNOSTIC_OUTPUT_LIMIT]
                + "<truncated>"
            )
        return repr(sanitized)

    lines: list[str] = []
    for ordinal, (returncode, stdout, stderr) in enumerate(results, start=1):
        signal = (
            f" (signal {-returncode})"
            if returncode is not None and returncode < 0
            else ""
        )
        lines.extend(
            (
                f"child {ordinal}: returncode={returncode!r}{signal}",
                f"  stdout={bounded_repr(stdout)}",
                f"  stderr={bounded_repr(stderr)}",
            )
        )
    return "\n".join(lines)


class _ClockAbort(BaseException):
    pass


class _FailOnceClock:
    def __init__(self, failure_call: int, failure: object) -> None:
        self._failure_call = failure_call
        self._failure = failure
        self.calls = 0

    def __call__(self) -> datetime:
        self.calls += 1
        if self.calls == self._failure_call:
            if isinstance(self._failure, BaseException):
                raise self._failure
            return cast(datetime, self._failure)
        return _START


class _RollbackFailureConnection:
    def rollback(self) -> None:
        raise sqlite3.OperationalError("secondary rollback failure")


def test_history_root_resolution_uses_absolute_override_xdg_and_home(
    tmp_path: Path,
) -> None:
    override = tmp_path / "override"
    assert resolve_history_root({HISTORY_DIRECTORY_ENV: str(override)}) == override
    assert resolve_history_root({"XDG_STATE_HOME": str(tmp_path / "state")}) == (
        tmp_path / "state" / "hiyelx" / "runtime-history"
    )
    assert resolve_history_root({"HOME": str(tmp_path / "home")}) == (
        tmp_path / "home" / ".local" / "state" / "hiyelx" / "runtime-history"
    )
    with pytest.raises(UnsafeHistoryPathError):
        resolve_history_root({HISTORY_DIRECTORY_ENV: "relative"})


def test_secondary_rollback_failure_never_masks_primary_exception() -> None:
    connection = cast(sqlite3.Connection, _RollbackFailureConnection())
    typed = RunNotFoundError()
    with pytest.raises(RunNotFoundError) as typed_caught:
        history._rollback_and_raise(  # pyright: ignore[reportPrivateUsage]
            connection,
            typed,
        )
    assert typed_caught.value is typed

    ordinary = RuntimeError("private primary failure")
    with pytest.raises(HistoryStoreError) as ordinary_caught:
        history._rollback_and_raise(  # pyright: ignore[reportPrivateUsage]
            connection,
            ordinary,
        )
    assert str(ordinary_caught.value) == ""
    assert ordinary_caught.value.__cause__ is ordinary

    base = _ClockAbort("primary abort")
    with pytest.raises(_ClockAbort) as base_caught:
        history._rollback_and_raise(  # pyright: ignore[reportPrivateUsage]
            connection,
            base,
        )
    assert base_caught.value is base


def test_secure_initialization_creates_private_schema_and_wal(tmp_path: Path) -> None:
    root = tmp_path / "history"
    store = open_writer(root=root, platform="linux")
    try:
        assert stat.S_IMODE(root.stat().st_mode) == 0o700
        assert stat.S_IMODE((root / "history.lock").stat().st_mode) == 0o600
        assert stat.S_IMODE((root / "history.sqlite3").stat().st_mode) == 0o600
        assert store._connection.execute(  # pyright: ignore[reportPrivateUsage]
            "PRAGMA user_version"
        ).fetchone() == (1,)
        assert store._connection.execute(  # pyright: ignore[reportPrivateUsage]
            "PRAGMA journal_mode"
        ).fetchone() == ("wal",)
        assert store._connection.execute(  # pyright: ignore[reportPrivateUsage]
            "PRAGMA synchronous"
        ).fetchone() == (2,)
        assert store._connection.execute(  # pyright: ignore[reportPrivateUsage]
            "PRAGMA foreign_keys"
        ).fetchone() == (1,)
        tables = {
            row[0]
            for row in store._connection.execute(  # pyright: ignore[reportPrivateUsage]
                "SELECT name FROM sqlite_schema WHERE type = 'table'"
            )
        }
        assert {"runs", "events"}.issubset(tables)
        for sidecar in ("history.sqlite3-wal", "history.sqlite3-shm"):
            path = root / sidecar
            if path.exists():
                assert stat.S_IMODE(path.stat().st_mode) == 0o600
        assert not (root / ".history.sqlite3.init").exists()
    finally:
        store.close()


def test_initialization_lock_is_released_and_two_writers_share_wal(tmp_path: Path) -> None:
    root = tmp_path / "history"
    first = open_writer(root=root, platform="linux")
    descriptor = os.open(root / "history.lock", os.O_RDWR)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        fcntl.flock(descriptor, fcntl.LOCK_UN)
    finally:
        os.close(descriptor)

    second = open_writer(root=root, platform="linux")
    try:
        first.create_run(
            session_id="alpha",
            config_fingerprint=_FINGERPRINT,
            package_version="0.2.0a1",
        )
        second.create_run(
            session_id="beta",
            config_fingerprint=_FINGERPRINT,
            package_version="0.2.0a1",
        )
        records = list_runs(root=root)
        assert {record.session_id for record in records} == {"alpha", "beta"}
        assert all(record.result is None for record in records)
    finally:
        second.close()
        first.close()


def test_sqlite_write_contention_is_bounded_and_sanitized(tmp_path: Path) -> None:
    root = tmp_path / "history"
    first = open_writer(root=root, platform="linux")
    second = open_writer(root=root, platform="linux")
    try:
        first._connection.execute("BEGIN IMMEDIATE")  # pyright: ignore[reportPrivateUsage]
        started = time.monotonic()
        with pytest.raises(HistoryStoreError) as caught:
            second.create_run(
                session_id="contended",
                config_fingerprint=_FINGERPRINT,
                package_version="0.2.0a1",
            )
        elapsed = time.monotonic() - started
        assert 0.5 <= elapsed < 3.0
        assert str(caught.value) == ""
        assert not second._connection.in_transaction  # pyright: ignore[reportPrivateUsage]
    finally:
        first._connection.rollback()  # pyright: ignore[reportPrivateUsage]
        second.close()
        first.close()


def test_event_write_contention_is_bounded_rolled_back_and_recoverable(
    tmp_path: Path,
) -> None:
    root = tmp_path / "history"
    identifiers = iter((uuid.UUID(_RUN_A), uuid.UUID(_RUN_B)))
    first = open_writer(
        root=root,
        run_id_factory=lambda: next(identifiers),
        clock=lambda: _START,
        platform="linux",
    )
    second = open_writer(
        root=root,
        run_id_factory=lambda: next(identifiers),
        clock=lambda: _START,
        platform="linux",
    )
    try:
        first.create_run(
            session_id="alpha",
            config_fingerprint=_FINGERPRINT,
            package_version="0.2.0a1",
        )
        second.create_run(
            session_id="beta",
            config_fingerprint=_FINGERPRINT,
            package_version="0.2.0a1",
        )
        first._connection.execute(  # pyright: ignore[reportPrivateUsage]
            "BEGIN IMMEDIATE"
        )
        started = time.monotonic()
        with pytest.raises(HistoryStoreError) as caught:
            second.persist_events(_RUN_B, _event_snapshot()[:1])
        elapsed = time.monotonic() - started
        assert 0.5 <= elapsed < 3.0
        assert str(caught.value) == ""
        assert not second._connection.in_transaction  # pyright: ignore[reportPrivateUsage]
        first._connection.rollback()  # pyright: ignore[reportPrivateUsage]

        assert second.get_run(_RUN_B).event_high_water_mark is None
        assert second.persist_events(_RUN_B, _event_snapshot()[:1]) == 0
    finally:
        if first._connection.in_transaction:  # pyright: ignore[reportPrivateUsage]
            first._connection.rollback()  # pyright: ignore[reportPrivateUsage]
        second.close()
        first.close()


def test_initialization_lock_contention_is_bounded_and_recoverable(tmp_path: Path) -> None:
    root = tmp_path / "history"
    bootstrap = open_writer(root=root)
    bootstrap.close()
    descriptor = os.open(root / "history.lock", os.O_RDWR)
    fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
    try:
        started = time.monotonic()
        with pytest.raises(HistoryStoreError) as caught:
            open_writer(root=root)
        elapsed = time.monotonic() - started
        assert 0.5 <= elapsed < 3.0
        assert str(caught.value) == ""
    finally:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)

    recovered = open_writer(root=root)
    recovered.close()


def test_child_process_diagnostics_are_bounded_ordered_and_sanitized(
    tmp_path: Path,
) -> None:
    results = (
        (0, "opened", ""),
        (7, f"failed at {tmp_path / 'history.sqlite3'}", "child error"),
        (-9, "x" * (_CHILD_DIAGNOSTIC_OUTPUT_LIMIT + 1), ""),
    )

    formatted = _format_child_process_diagnostics(results, task_root=tmp_path)

    assert formatted.index("child 1:") < formatted.index("child 2:")
    assert formatted.index("child 2:") < formatted.index("child 3:")
    assert "child 1: returncode=0" in formatted
    assert "stdout='opened'" in formatted
    assert "stderr=''" in formatted
    assert "child 2: returncode=7" in formatted
    assert "<redacted-path>" in formatted
    assert str(tmp_path) not in formatted
    assert "stderr='child error'" in formatted
    assert "child 3: returncode=-9 (signal 9)" in formatted
    assert "<truncated>" in formatted
    assert len(formatted.splitlines()[6]) <= _CHILD_DIAGNOSTIC_OUTPUT_LIMIT + 40


def test_concurrent_first_initialization_is_bounded_and_recoverable(
    tmp_path: Path,
) -> None:
    root = tmp_path / "history"
    gate = tmp_path / "start"
    script = """
import os
import sys
import time
from pathlib import Path
from hiyelx.runtime.history import HistoryStoreError, open_writer

gate = Path(sys.argv[1])
root = Path(sys.argv[2])
deadline = time.monotonic() + 5
while not gate.exists():
    if time.monotonic() >= deadline:
        raise SystemExit(2)
    time.sleep(0.005)
try:
    store = open_writer(root=root)
except HistoryStoreError:
    print("rejected", flush=True)
else:
    print("opened", flush=True)
    time.sleep(0.2)
    store.close()
"""
    processes = tuple(
        subprocess.Popen(
            [sys.executable, "-c", script, str(gate), str(root)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        for _ in range(2)
    )
    gate.touch()
    results = tuple(process.communicate(timeout=10) for process in processes)
    child_results = tuple(
        (process.returncode, stdout, stderr)
        for process, (stdout, stderr) in zip(processes, results, strict=True)
    )

    assert all(returncode == 0 for returncode, _stdout, _stderr in child_results), (
        "concurrent initialization child process failure:\n"
        + _format_child_process_diagnostics(child_results, task_root=tmp_path)
    )
    outcomes = {stdout.strip() for stdout, _stderr in results}
    assert "opened" in outcomes
    assert outcomes <= {"opened", "rejected"}
    assert all(stderr == "" for _stdout, stderr in results)
    recovered = open_writer(root=root)
    recovered.close()


@pytest.mark.parametrize("artifact", ("history.lock", "history.sqlite3"))
def test_symlinked_artifacts_are_rejected(tmp_path: Path, artifact: str) -> None:
    root = tmp_path / "history"
    root.mkdir(mode=0o700)
    target = tmp_path / "target"
    target.write_bytes(b"")
    (root / artifact).symlink_to(target)
    with pytest.raises(UnsafeHistoryPathError):
        open_writer(root=root)


def test_wrong_type_and_unsafe_permissions_are_rejected(tmp_path: Path) -> None:
    wrong_type = tmp_path / "wrong-type"
    wrong_type.mkdir(mode=0o700)
    (wrong_type / "history.lock").mkdir(mode=0o700)
    with pytest.raises(UnsafeHistoryPathError):
        open_writer(root=wrong_type)

    unsafe = tmp_path / "unsafe"
    unsafe.mkdir(mode=0o700)
    (unsafe / "history.lock").write_bytes(b"")
    os.chmod(unsafe / "history.lock", 0o644)
    with pytest.raises(UnsafeHistoryPathError):
        open_writer(root=unsafe)

    unsafe_root = tmp_path / "unsafe-root"
    unsafe_root.mkdir(mode=0o755)
    with pytest.raises(UnsafeHistoryPathError):
        open_writer(root=unsafe_root)


def test_foreign_uid_is_rejected_before_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "history"
    root.mkdir(mode=0o700)
    before = root.stat()
    monkeypatch.setattr(history.os, "geteuid", lambda: before.st_uid + 1)

    with pytest.raises(UnsafeHistoryPathError):
        open_writer(root=root)

    assert tuple(root.iterdir()) == ()


def test_unknown_entry_causes_zero_mutation(tmp_path: Path) -> None:
    root = tmp_path / "history"
    root.mkdir(mode=0o700)
    unknown = root / "unrelated"
    unknown.write_text("keep", encoding="utf-8")
    os.chmod(unknown, 0o600)
    before = _snapshot(root)

    with pytest.raises(UnsafeHistoryPathError):
        open_writer(root=root)

    assert _snapshot(root) == before


@pytest.mark.parametrize(
    "artifact",
    (".history.sqlite3.init", "history.sqlite3-wal", "history.sqlite3-shm"),
)
def test_partial_store_is_not_treated_as_missing(
    tmp_path: Path,
    artifact: str,
) -> None:
    root = tmp_path / "history"
    root.mkdir(mode=0o700)
    partial = root / artifact
    partial.write_bytes(b"")
    os.chmod(partial, 0o600)
    before = _snapshot(root)

    with pytest.raises(HistoryStoreError):
        list_runs(root=root)
    with pytest.raises(HistoryStoreError):
        open_writer(root=root)

    assert _snapshot(root) == before


def test_init_artifact_fails_closed_without_mutating_valid_database(
    tmp_path: Path,
) -> None:
    root = tmp_path / "history"
    store = open_writer(root=root)
    store.close()
    temporary = root / ".history.sqlite3.init"
    temporary.write_bytes(b"partial private initialization")
    os.chmod(temporary, 0o600)
    before = _snapshot(root)

    with pytest.raises(HistoryStoreError) as read_error:
        list_runs(root=root)
    with pytest.raises(HistoryStoreError) as write_error:
        open_writer(root=root)

    assert str(read_error.value) == ""
    assert str(write_error.value) == ""
    assert _snapshot(root) == before


def test_injected_values_create_finalize_and_reject_second_finalization(
    tmp_path: Path,
) -> None:
    times = iter((_START, _START + timedelta(seconds=5)))
    store = open_writer(
        root=tmp_path / "history",
        run_id_factory=lambda: uuid.UUID(_RUN_A),
        clock=lambda: next(times),
        platform="linux",
    )
    try:
        created = store.create_run(
            session_id="alpha",
            config_fingerprint=_FINGERPRINT,
            package_version="0.2.0a1",
        )
        assert created.run_id == _RUN_A
        assert created.started_at == "2026-10-18T10:11:12.123456Z"
        assert created.platform == "linux"
        assert created.result is None

        finalized = store.finalize_run(
            _RUN_A,
            result=RunResult.COMPLETED,
            stop_reason=StopReason.CLI_STOP,
            event_high_water_mark=None,
        )
        assert finalized.ended_at == "2026-10-18T10:11:17.123456Z"
        assert finalized.result is RunResult.COMPLETED
        assert finalized.stop_reason is StopReason.CLI_STOP
        assert finalized.event_high_water_mark is None
        with pytest.raises(RunAlreadyFinalizedError):
            store.finalize_run(
                _RUN_A,
                result=RunResult.INTERRUPTED,
                stop_reason=StopReason.SIGINT,
                event_high_water_mark=None,
            )
    finally:
        store.close()


def test_event_batch_is_atomic_updates_watermark_and_uses_injected_clock(
    tmp_path: Path,
) -> None:
    times = iter(
        (
            _START,
            _START + timedelta(seconds=1),
            _START + timedelta(seconds=1),
            _START - timedelta(seconds=1),
        )
    )
    root = tmp_path / "history"
    store = open_writer(
        root=root,
        run_id_factory=lambda: uuid.UUID(_RUN_A),
        clock=lambda: next(times),
        platform="linux",
    )
    events = _event_snapshot()
    try:
        store.create_run(
            session_id="alpha",
            config_fingerprint=_FINGERPRINT,
            package_version="0.2.0a1",
        )
        assert store.persist_events(_RUN_A, events) == 2
        assert store.get_run(_RUN_A).event_high_water_mark == 2
        records = store.list_events(_RUN_A)
        assert tuple(record.sequence for record in records) == (0, 1, 2)
        assert tuple(record.severity for record in records) == (
            "info",
            "error",
            "warning",
        )
        assert tuple(record.recorded_at for record in records) == (
            "2026-10-18T10:11:13.123456Z",
            "2026-10-18T10:11:13.123456Z",
            "2026-10-18T10:11:11.123456Z",
        )
    finally:
        store.close()


@pytest.mark.parametrize(
    "failure",
    (RuntimeError("clock failed"), object()),
    ids=("ordinary-exception", "invalid-return"),
)
def test_event_clock_failure_is_sanitized_rolled_back_and_recoverable(
    tmp_path: Path,
    failure: object,
) -> None:
    clock = _FailOnceClock(2, failure)
    store = open_writer(
        root=tmp_path / "history",
        run_id_factory=lambda: uuid.UUID(_RUN_A),
        clock=clock,
        platform="linux",
    )
    try:
        store.create_run(
            session_id="alpha",
            config_fingerprint=_FINGERPRINT,
            package_version="0.2.0a1",
        )
        with pytest.raises(HistoryStoreError) as caught:
            store.persist_events(_RUN_A, _event_snapshot()[:1])
        assert str(caught.value) == ""
        assert not store._connection.in_transaction  # pyright: ignore[reportPrivateUsage]
        assert store._connection.execute(  # pyright: ignore[reportPrivateUsage]
            "SELECT count(*) FROM events"
        ).fetchone() == (0,)
        assert store.get_run(_RUN_A).event_high_water_mark is None

        assert store.persist_events(_RUN_A, _event_snapshot()[:1]) == 0
        assert store.get_run(_RUN_A).event_high_water_mark == 0
    finally:
        store.close()


def test_mid_batch_clock_failure_rolls_back_and_explicit_retry_succeeds(
    tmp_path: Path,
) -> None:
    clock = _FailOnceClock(3, RuntimeError("clock failed"))
    store = open_writer(
        root=tmp_path / "history",
        run_id_factory=lambda: uuid.UUID(_RUN_A),
        clock=clock,
        platform="linux",
    )
    try:
        store.create_run(
            session_id="alpha",
            config_fingerprint=_FINGERPRINT,
            package_version="0.2.0a1",
        )
        with pytest.raises(HistoryStoreError) as caught:
            store.persist_events(_RUN_A, _event_snapshot())
        assert str(caught.value) == ""
        assert not store._connection.in_transaction  # pyright: ignore[reportPrivateUsage]
        assert store._connection.execute(  # pyright: ignore[reportPrivateUsage]
            "SELECT count(*) FROM events"
        ).fetchone() == (0,)
        assert store.get_run(_RUN_A).event_high_water_mark is None

        assert store.persist_events(_RUN_A, _event_snapshot()) == 2
        assert store.get_run(_RUN_A).event_high_water_mark == 2
    finally:
        store.close()


def test_event_clock_base_exception_is_preserved_and_rolled_back(
    tmp_path: Path,
) -> None:
    failure = _ClockAbort("clock aborted")
    clock = _FailOnceClock(3, failure)
    store = open_writer(
        root=tmp_path / "history",
        run_id_factory=lambda: uuid.UUID(_RUN_A),
        clock=clock,
        platform="linux",
    )
    try:
        store.create_run(
            session_id="alpha",
            config_fingerprint=_FINGERPRINT,
            package_version="0.2.0a1",
        )
        with pytest.raises(_ClockAbort) as caught:
            store.persist_events(_RUN_A, _event_snapshot())
        assert caught.value is failure
        assert not store._connection.in_transaction  # pyright: ignore[reportPrivateUsage]
        assert store._connection.execute(  # pyright: ignore[reportPrivateUsage]
            "SELECT count(*) FROM events"
        ).fetchone() == (0,)
        assert store.get_run(_RUN_A).event_high_water_mark is None
    finally:
        store.close()


@pytest.mark.parametrize(
    "failure",
    (RuntimeError("clock failed"), object()),
    ids=("ordinary-exception", "invalid-return"),
)
def test_finalize_clock_failure_is_sanitized_rolled_back_and_recoverable(
    tmp_path: Path,
    failure: object,
) -> None:
    clock = _FailOnceClock(2, failure)
    store = open_writer(
        root=tmp_path / "history",
        run_id_factory=lambda: uuid.UUID(_RUN_A),
        clock=clock,
        platform="linux",
    )
    try:
        store.create_run(
            session_id="alpha",
            config_fingerprint=_FINGERPRINT,
            package_version="0.2.0a1",
        )
        with pytest.raises(HistoryStoreError) as caught:
            store.finalize_run(
                _RUN_A,
                result=RunResult.COMPLETED,
                stop_reason=StopReason.CLI_STOP,
                event_high_water_mark=None,
            )
        assert str(caught.value) == ""
        assert not store._connection.in_transaction  # pyright: ignore[reportPrivateUsage]
        incomplete = store.get_run(_RUN_A)
        assert incomplete.ended_at is None
        assert incomplete.result is None
        assert incomplete.stop_reason is None

        finalized = store.finalize_run(
            _RUN_A,
            result=RunResult.COMPLETED,
            stop_reason=StopReason.CLI_STOP,
            event_high_water_mark=None,
        )
        assert finalized.result is RunResult.COMPLETED
        with pytest.raises(RunAlreadyFinalizedError):
            store.finalize_run(
                _RUN_A,
                result=RunResult.COMPLETED,
                stop_reason=StopReason.CLI_STOP,
                event_high_water_mark=None,
            )
    finally:
        store.close()


def test_finalize_clock_base_exception_is_preserved_and_rolled_back(
    tmp_path: Path,
) -> None:
    failure = _ClockAbort("clock aborted")
    clock = _FailOnceClock(2, failure)
    store = open_writer(
        root=tmp_path / "history",
        run_id_factory=lambda: uuid.UUID(_RUN_A),
        clock=clock,
        platform="linux",
    )
    try:
        store.create_run(
            session_id="alpha",
            config_fingerprint=_FINGERPRINT,
            package_version="0.2.0a1",
        )
        with pytest.raises(_ClockAbort) as caught:
            store.finalize_run(
                _RUN_A,
                result=RunResult.COMPLETED,
                stop_reason=StopReason.CLI_STOP,
                event_high_water_mark=None,
            )
        assert caught.value is failure
        assert not store._connection.in_transaction  # pyright: ignore[reportPrivateUsage]
        incomplete = store.get_run(_RUN_A)
        assert incomplete.ended_at is None
        assert incomplete.result is None
        assert incomplete.stop_reason is None
    finally:
        store.close()


def test_event_batch_rollback_leaves_zero_rows_and_watermark(tmp_path: Path) -> None:
    root = tmp_path / "history"
    store = open_writer(
        root=root,
        run_id_factory=lambda: uuid.UUID(_RUN_A),
        clock=lambda: _START,
        platform="linux",
    )
    try:
        store.create_run(
            session_id="alpha",
            config_fingerprint=_FINGERPRINT,
            package_version="0.2.0a1",
        )
        store._connection.execute(  # pyright: ignore[reportPrivateUsage]
            """
            CREATE TEMP TRIGGER fail_second_event
            BEFORE INSERT ON events WHEN NEW.sequence = 1
            BEGIN SELECT RAISE(ABORT, 'private failure'); END
            """
        )
        with pytest.raises(HistoryStoreError) as caught:
            store.persist_events(_RUN_A, _event_snapshot()[:2])
        assert str(caught.value) == ""
        assert store._connection.execute(  # pyright: ignore[reportPrivateUsage]
            "SELECT count(*) FROM events"
        ).fetchone() == (0,)
        assert store.get_run(_RUN_A).event_high_water_mark is None
    finally:
        store.close()


def test_event_sequence_gap_backward_and_conflicting_prefix_are_rejected(
    tmp_path: Path,
) -> None:
    root = tmp_path / "history"
    store = open_writer(
        root=root,
        run_id_factory=lambda: uuid.UUID(_RUN_A),
        clock=lambda: _START,
        platform="linux",
    )
    try:
        store.create_run(
            session_id="alpha",
            config_fingerprint=_FINGERPRINT,
            package_version="0.2.0a1",
        )
        snapshot = _event_snapshot()
        with pytest.raises(HistoryStoreError):
            store.persist_events(_RUN_A, (snapshot[0], snapshot[2]))
        store.persist_events(_RUN_A, snapshot[:1])
        with pytest.raises(HistoryStoreError):
            store.persist_events(_RUN_A, ())
        conflicting = RuntimeEvent(
            sequence=0,
            operation=RuntimeEventOperation.RUNTIME_START,
            outcome=RuntimeEventOutcome.REQUESTED,
            summary="runtime start requested",
        )
        assert conflicting == snapshot[0]
        assert store.persist_events(_RUN_A, (conflicting,)) == 0
        changed = RuntimeEvent(
            sequence=0,
            operation=RuntimeEventOperation.RUNTIME_SHUTDOWN,
            outcome=RuntimeEventOutcome.REQUESTED,
            summary="runtime shutdown requested",
        )
        with pytest.raises(HistoryStoreError):
            store.persist_events(_RUN_A, (changed,))
        with pytest.raises(RunNotFoundError):
            store.persist_events(_RUN_B, snapshot[:1])
    finally:
        store.close()


def test_finalized_run_rejects_event_writes_without_mutation(tmp_path: Path) -> None:
    store = open_writer(
        root=tmp_path / "history",
        run_id_factory=lambda: uuid.UUID(_RUN_A),
        clock=lambda: _START,
        platform="linux",
    )
    try:
        store.create_run(
            session_id="alpha",
            config_fingerprint=_FINGERPRINT,
            package_version="0.2.0a1",
        )
        snapshot = _event_snapshot()[:1]
        store.persist_events(_RUN_A, snapshot)
        store.finalize_run(
            _RUN_A,
            result=RunResult.COMPLETED,
            stop_reason=StopReason.CLI_STOP,
            event_high_water_mark=0,
        )
        with pytest.raises(RunAlreadyFinalizedError):
            store.persist_events(_RUN_A, snapshot)
        assert not store._connection.in_transaction  # pyright: ignore[reportPrivateUsage]
        assert tuple(event.sequence for event in store.list_events(_RUN_A)) == (0,)
        assert store.get_run(_RUN_A).event_high_water_mark == 0
    finally:
        store.close()


@pytest.mark.parametrize(
    "event",
    (
        RuntimeEvent(
            0,
            RuntimeEventOperation.RUNTIME_START,
            RuntimeEventOutcome.REQUESTED,
            "private arbitrary summary",
        ),
        RuntimeEvent(
            0,
            RuntimeEventOperation.RESOURCE_START,
            RuntimeEventOutcome.ATTEMPTED,
            "resource start attempted",
        ),
        RuntimeEvent(
            0,
            RuntimeEventOperation.RUNTIME_START,
            RuntimeEventOutcome.REQUESTED,
            "runtime start requested",
            identity=ResourceIdentity("unsafe\nidentity"),
            lifecycle_state=LifecycleState.CREATED,
            health_status=HealthStatus.UNKNOWN,
        ),
        RuntimeEvent(
            0,
            cast(RuntimeEventOperation, "invalid_operation"),
            RuntimeEventOutcome.REQUESTED,
            "runtime start requested",
        ),
        RuntimeEvent(
            0,
            RuntimeEventOperation.RESOURCE_START,
            RuntimeEventOutcome.ATTEMPTED,
            "resource start attempted",
            identity=ResourceIdentity("sim_motor"),
            lifecycle_state=cast(LifecycleState, "invalid_state"),
            health_status=HealthStatus.UNKNOWN,
        ),
        RuntimeEvent(
            0,
            RuntimeEventOperation.RESOURCE_START,
            RuntimeEventOutcome.ATTEMPTED,
            "resource start attempted",
            identity=ResourceIdentity("sim_motor"),
            lifecycle_state=LifecycleState.CREATED,
            health_status=cast(HealthStatus, "invalid_health"),
        ),
    ),
)
def test_invalid_event_contract_is_rejected_before_write(
    tmp_path: Path,
    event: RuntimeEvent,
) -> None:
    store = open_writer(
        root=tmp_path / "history",
        run_id_factory=lambda: uuid.UUID(_RUN_A),
        clock=lambda: _START,
        platform="linux",
    )
    try:
        store.create_run(
            session_id="alpha",
            config_fingerprint=_FINGERPRINT,
            package_version="0.2.0a1",
        )
        with pytest.raises(HistoryStoreError):
            store.persist_events(_RUN_A, (event,))
        assert store.get_run(_RUN_A).event_high_water_mark is None
    finally:
        store.close()


def test_event_query_is_ordered_bounded_and_uses_exclusive_cursor(
    tmp_path: Path,
) -> None:
    root = tmp_path / "history"
    store = open_writer(
        root=root,
        run_id_factory=lambda: uuid.UUID(_RUN_A),
        clock=lambda: _START,
        platform="linux",
    )
    try:
        store.create_run(
            session_id="alpha",
            config_fingerprint=_FINGERPRINT,
            package_version="0.2.0a1",
        )
        store.persist_events(_RUN_A, _event_snapshot())
    finally:
        store.close()

    assert DEFAULT_EVENT_LIMIT == 100
    assert tuple(record.sequence for record in list_events(_RUN_A, root=root)) == (
        0,
        1,
        2,
    )
    assert tuple(
        record.sequence
        for record in list_events(_RUN_A, root=root, after=0, limit=1)
    ) == (1,)
    assert len(list_events(_RUN_A, root=root, limit=1)) == 1
    assert len(list_events(_RUN_A, root=root, limit=100)) == 3
    assert list_events(_RUN_A, root=root, after=2) == ()
    assert list_events(_RUN_A, root=root, after=10**100) == ()
    assert len(list_events(_RUN_A, root=root, limit=1000)) == 3
    for invalid in (-2, True):
        with pytest.raises(InvalidEventCursorError):
            list_events(_RUN_A, root=root, after=invalid)  # type: ignore[arg-type]
    for invalid in (0, 1001, True):
        with pytest.raises(InvalidEventLimitError):
            list_events(_RUN_A, root=root, limit=invalid)  # type: ignore[arg-type]


def test_event_query_handles_empty_incomplete_finalized_and_unknown_runs(
    tmp_path: Path,
) -> None:
    root = tmp_path / "history"
    store = open_writer(
        root=root,
        run_id_factory=lambda: uuid.UUID(_RUN_A),
        clock=lambda: _START,
        platform="linux",
    )
    try:
        store.create_run(
            session_id="alpha",
            config_fingerprint=_FINGERPRINT,
            package_version="0.2.0a1",
        )
        assert store.list_events(_RUN_A) == ()
        assert not store._connection.in_transaction  # pyright: ignore[reportPrivateUsage]
        store.finalize_run(
            _RUN_A,
            result=RunResult.COMPLETED,
            stop_reason=StopReason.CLI_STOP,
            event_high_water_mark=None,
        )
        assert store.list_events(_RUN_A) == ()
        assert not store._connection.in_transaction  # pyright: ignore[reportPrivateUsage]
        with pytest.raises(RunNotFoundError):
            store.list_events(_RUN_B)
        assert not store._connection.in_transaction  # pyright: ignore[reportPrivateUsage]
        with pytest.raises(InvalidRunIdError):
            store.list_events("not-a-run")
        assert not store._connection.in_transaction  # pyright: ignore[reportPrivateUsage]
    finally:
        store.close()


@pytest.mark.parametrize(
    "failure",
    (RuntimeError("decode failed"), _ClockAbort("decode aborted")),
    ids=("ordinary-exception", "base-exception"),
)
def test_event_read_transaction_rolls_back_and_preserves_exception_contract(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure: BaseException,
) -> None:
    store = open_writer(
        root=tmp_path / "history",
        run_id_factory=lambda: uuid.UUID(_RUN_A),
        clock=lambda: _START,
        platform="linux",
    )
    try:
        store.create_run(
            session_id="alpha",
            config_fingerprint=_FINGERPRINT,
            package_version="0.2.0a1",
        )
        store.persist_events(_RUN_A, _event_snapshot()[:1])
        original_decode = history._decode_event  # pyright: ignore[reportPrivateUsage]

        def fail_decode(_row: tuple[object, ...]) -> EventRecord:
            raise failure

        monkeypatch.setattr(history, "_decode_event", fail_decode)
        if isinstance(failure, Exception):
            with pytest.raises(HistoryStoreError) as caught:
                store.list_events(_RUN_A)
            assert str(caught.value) == ""
            assert caught.value.__cause__ is failure
        else:
            with pytest.raises(_ClockAbort) as caught:
                store.list_events(_RUN_A)
            assert caught.value is failure
        assert not store._connection.in_transaction  # pyright: ignore[reportPrivateUsage]

        monkeypatch.setattr(history, "_decode_event", original_decode)
        assert tuple(event.sequence for event in store.list_events(_RUN_A)) == (0,)
    finally:
        store.close()


def test_event_query_is_read_only_and_rejects_corrupt_selected_row(
    tmp_path: Path,
) -> None:
    root = tmp_path / "history"
    store = open_writer(
        root=root,
        run_id_factory=lambda: uuid.UUID(_RUN_A),
        clock=lambda: _START,
        platform="linux",
    )
    store.create_run(
        session_id="alpha",
        config_fingerprint=_FINGERPRINT,
        package_version="0.2.0a1",
    )
    store.persist_events(_RUN_A, _event_snapshot())
    store.close()
    before = _snapshot(root)

    assert len(list_events(_RUN_A, root=root)) == 3
    assert _snapshot(root) == before

    connection = sqlite3.connect(root / "history.sqlite3")
    connection.execute("PRAGMA ignore_check_constraints = ON")
    connection.execute(
        "UPDATE events SET summary = ? WHERE sequence = 1",
        ("private\nsummary",),
    )
    connection.commit()
    connection.close()
    with pytest.raises(HistoryStoreError):
        list_events(_RUN_A, root=root)


@pytest.mark.parametrize(
    ("column", "value"),
    (
        ("schema_version", 2),
        ("run_id", _RUN_B),
        ("sequence", 9),
        ("resource_identity", "unsafe\nidentity"),
        ("event_type", "unknown"),
        ("outcome", "unknown"),
        ("severity", "debug"),
        ("summary", "private\nsummary"),
        ("lifecycle_state", "unknown"),
        ("health_status", "unknown"),
        ("recorded_at", "not-a-timestamp"),
    ),
)
def test_each_corrupt_event_field_fails_closed_and_closes_read_transaction(
    tmp_path: Path,
    column: str,
    value: object,
) -> None:
    root = tmp_path / "history"
    store = open_writer(
        root=root,
        run_id_factory=lambda: uuid.UUID(_RUN_A),
        clock=lambda: _START,
        platform="linux",
    )
    try:
        store.create_run(
            session_id="alpha",
            config_fingerprint=_FINGERPRINT,
            package_version="0.2.0a1",
        )
        store.persist_events(_RUN_A, _event_snapshot()[:1])
        connection = sqlite3.connect(root / "history.sqlite3")
        try:
            connection.execute("PRAGMA ignore_check_constraints = ON")
            connection.execute(
                f"UPDATE events SET {column} = ? WHERE sequence = 0",  # noqa: S608
                (value,),
            )
            connection.commit()
        finally:
            connection.close()

        with pytest.raises(HistoryStoreError) as caught:
            store.list_events(_RUN_A, limit=1)
        assert str(caught.value) == ""
        assert not store._connection.in_transaction  # pyright: ignore[reportPrivateUsage]
    finally:
        store.close()


def test_summary_allowlist_exactly_matches_runtime_manager_static_emissions() -> None:
    tree = ast.parse(textwrap.dedent(inspect.getsource(RuntimeManager)))
    emitted: set[tuple[RuntimeEventOperation, RuntimeEventOutcome, str]] = set()
    for node in ast.walk(tree):
        if (
            not isinstance(node, ast.Call)
            or not isinstance(node.func, ast.Attribute)
            or node.func.attr not in {"_emit", "_emit_resource"}
        ):
            continue
        keywords = {keyword.arg: keyword.value for keyword in node.keywords}
        operation = keywords.get("operation")
        outcome = keywords.get("outcome")
        summary = keywords.get("summary")
        if not (
            isinstance(operation, ast.Attribute)
            and isinstance(outcome, ast.Attribute)
            and isinstance(summary, ast.Constant)
            and isinstance(summary.value, str)
        ):
            continue
        emitted.add(
            (
                RuntimeEventOperation[operation.attr],
                RuntimeEventOutcome[outcome.attr],
                summary.value,
            )
        )

    assert emitted == runtime_events._ALLOWED_EVENT_SUMMARIES  # pyright: ignore[reportPrivateUsage]


def test_active_writer_reader_and_distinct_writers_share_event_store(
    tmp_path: Path,
) -> None:
    root = tmp_path / "history"
    identifiers = iter((uuid.UUID(_RUN_A), uuid.UUID(_RUN_B)))
    first = open_writer(
        root=root,
        run_id_factory=lambda: next(identifiers),
        clock=lambda: _START,
        platform="linux",
    )
    second = open_writer(
        root=root,
        run_id_factory=lambda: next(identifiers),
        clock=lambda: _START,
        platform="linux",
    )
    try:
        first.create_run(
            session_id="alpha",
            config_fingerprint=_FINGERPRINT,
            package_version="0.2.0a1",
        )
        second.create_run(
            session_id="beta",
            config_fingerprint=_FINGERPRINT,
            package_version="0.2.0a1",
        )
        first.persist_events(_RUN_A, _event_snapshot()[:1])
        second.persist_events(_RUN_B, _event_snapshot()[:2])
        assert tuple(record.sequence for record in list_events(_RUN_A, root=root)) == (
            0,
        )
        assert tuple(record.sequence for record in list_events(_RUN_B, root=root)) == (
            0,
            1,
        )
    finally:
        second.close()
        first.close()


def test_missing_event_store_and_unknown_run_do_not_create_files(tmp_path: Path) -> None:
    root = tmp_path / "missing"
    with pytest.raises(RunNotFoundError):
        list_events(_RUN_A, root=root)
    assert not root.exists()


def _event_snapshot() -> tuple[RuntimeEvent, ...]:
    return (
        RuntimeEvent(
            0,
            RuntimeEventOperation.RUNTIME_START,
            RuntimeEventOutcome.REQUESTED,
            "runtime start requested",
        ),
        RuntimeEvent(
            1,
            RuntimeEventOperation.RUNTIME_FAILED,
            RuntimeEventOutcome.FAILED,
            "runtime failed during startup",
        ),
        RuntimeEvent(
            2,
            RuntimeEventOperation.HEALTH_DEGRADATION,
            RuntimeEventOutcome.FAILED,
            "resource health degraded after safe-stop failure",
            identity=ResourceIdentity("sim_motor"),
            lifecycle_state=LifecycleState.RUNNING,
            health_status=HealthStatus.DEGRADED,
        ),
    )


def _seed_prune_store(
    root: Path,
    run_ids: tuple[str, ...],
    *,
    finalized_count: int,
) -> None:
    identifiers = iter(uuid.UUID(run_id) for run_id in run_ids)
    store = open_writer(
        root=root,
        run_id_factory=lambda: next(identifiers),
        clock=lambda: _START,
        platform="linux",
    )
    try:
        for index, run_id in enumerate(run_ids):
            store.create_run(
                session_id=f"session-{index}",
                config_fingerprint=_FINGERPRINT,
                package_version="0.2.0a1",
            )
            if index < finalized_count:
                store.persist_events(run_id, _event_snapshot()[:1])
                store.finalize_run(
                    run_id,
                    result=RunResult.COMPLETED,
                    stop_reason=StopReason.CLI_STOP,
                    event_high_water_mark=0,
                )
    finally:
        store.close()


@pytest.mark.parametrize(
    ("keep", "expected_deleted", "retained_finalized"),
    (
        (0, 4, ()),
        (1, 3, (_RUN_D,)),
        (2, 2, (_RUN_D, _RUN_C)),
        (4, 0, (_RUN_D, _RUN_C, _RUN_B, _RUN_A)),
        ((1 << 63) - 1, 0, (_RUN_D, _RUN_C, _RUN_B, _RUN_A)),
    ),
)
def test_prune_retains_newest_finalized_runs_and_all_incomplete_runs(
    tmp_path: Path,
    keep: int,
    expected_deleted: int,
    retained_finalized: tuple[str, ...],
) -> None:
    root = tmp_path / f"history-{keep}"
    run_ids = (_RUN_A, _RUN_B, _RUN_C, _RUN_D, _RUN_E)
    _seed_prune_store(root, run_ids, finalized_count=4)

    assert prune_runs(root=root, keep=keep) == expected_deleted

    records = list_runs(root=root)
    assert tuple(
        record.run_id for record in records if record.result is not None
    ) == retained_finalized
    incomplete = get_run(_RUN_E, root=root)
    assert incomplete.result is None
    assert incomplete.ended_at is None
    for run_id in (_RUN_A, _RUN_B, _RUN_C, _RUN_D):
        if run_id in retained_finalized:
            assert tuple(event.sequence for event in list_events(run_id, root=root)) == (
                0,
            )
        else:
            with pytest.raises(RunNotFoundError):
                get_run(run_id, root=root)
            with pytest.raises(RunNotFoundError):
                list_events(run_id, root=root)


def test_prune_zero_finalized_runs_and_keep_validation(tmp_path: Path) -> None:
    root = tmp_path / "history"
    _seed_prune_store(root, (_RUN_A,), finalized_count=0)
    assert prune_runs(root=root, keep=0) == 0
    assert get_run(_RUN_A, root=root).result is None
    assert validate_retention_keep(0) == 0
    assert validate_retention_keep((1 << 63) - 1) == (1 << 63) - 1
    for invalid in (-1, 1 << 63, True):
        with pytest.raises(InvalidRetentionKeepError):
            validate_retention_keep(invalid)  # type: ignore[arg-type]


def test_prune_uses_started_at_before_run_id_across_sessions(tmp_path: Path) -> None:
    root = tmp_path / "history"
    identifiers = iter((uuid.UUID(_RUN_D), uuid.UUID(_RUN_A)))
    times = iter(
        (
            _START,
            _START + timedelta(seconds=10),
            _START + timedelta(seconds=1),
            _START + timedelta(seconds=11),
        )
    )
    store = open_writer(
        root=root,
        run_id_factory=lambda: next(identifiers),
        clock=lambda: next(times),
        platform="linux",
    )
    try:
        for session, run_id in (("first-session", _RUN_D), ("second-session", _RUN_A)):
            store.create_run(
                session_id=session,
                config_fingerprint=_FINGERPRINT,
                package_version="0.2.0a1",
            )
            store.finalize_run(
                run_id,
                result=RunResult.COMPLETED,
                stop_reason=StopReason.CLI_STOP,
                event_high_water_mark=None,
            )
    finally:
        store.close()

    assert prune_runs(root=root, keep=1) == 1
    assert tuple(record.run_id for record in list_runs(root=root)) == (_RUN_A,)


def test_prune_missing_and_empty_store_are_mutation_free(tmp_path: Path) -> None:
    missing = tmp_path / "missing"
    assert prune_runs(root=missing, keep=0) == 0
    assert not missing.exists()

    empty = tmp_path / "empty"
    empty.mkdir(mode=0o700)
    before = (empty.stat().st_ino, empty.stat().st_mode, empty.stat().st_mtime_ns)
    assert prune_runs(root=empty, keep=0) == 0
    after = (empty.stat().st_ino, empty.stat().st_mode, empty.stat().st_mtime_ns)
    assert before == after
    assert tuple(empty.iterdir()) == ()


def test_prune_mid_delete_failure_rolls_back_and_connection_recovers(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "history"
    _seed_prune_store(root, (_RUN_A, _RUN_B, _RUN_C), finalized_count=3)
    store = history._open_existing_writer(root=root)  # pyright: ignore[reportPrivateUsage]
    assert store is not None
    original_delete = history._delete_run_for_prune  # pyright: ignore[reportPrivateUsage]
    calls = 0

    def fail_second(connection: sqlite3.Connection, run_id: str) -> sqlite3.Cursor:
        nonlocal calls
        calls += 1
        cursor = original_delete(connection, run_id)
        if calls == 2:
            raise RuntimeError("private delete failure")
        return cursor

    monkeypatch.setattr(history, "_delete_run_for_prune", fail_second)
    try:
        with pytest.raises(HistoryStoreError) as caught:
            store.prune_finalized_runs(keep=0)
        assert str(caught.value) == ""
        assert not store._connection.in_transaction  # pyright: ignore[reportPrivateUsage]
        assert len(store.list_runs()) == 3
        assert sum(len(store.list_events(run_id)) for run_id in (_RUN_A, _RUN_B, _RUN_C)) == 3

        monkeypatch.setattr(history, "_delete_run_for_prune", original_delete)
        assert store.prune_finalized_runs(keep=0) == 3
        assert store.list_runs() == ()
    finally:
        store.close()


def test_prune_commit_failure_rolls_back_and_connection_recovers(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "history"
    _seed_prune_store(root, (_RUN_A, _RUN_B), finalized_count=2)
    store = history._open_existing_writer(root=root)  # pyright: ignore[reportPrivateUsage]
    assert store is not None
    original_commit = history._commit_prune  # pyright: ignore[reportPrivateUsage]

    def fail_commit(_connection: sqlite3.Connection) -> None:
        raise sqlite3.OperationalError("private commit failure")

    monkeypatch.setattr(history, "_commit_prune", fail_commit)
    try:
        with pytest.raises(HistoryStoreError) as caught:
            store.prune_finalized_runs(keep=0)
        assert str(caught.value) == ""
        assert not store._connection.in_transaction  # pyright: ignore[reportPrivateUsage]
        assert len(store.list_runs()) == 2

        monkeypatch.setattr(history, "_commit_prune", original_commit)
        assert store.prune_finalized_runs(keep=1) == 1
        assert tuple(record.run_id for record in store.list_runs()) == (_RUN_B,)
    finally:
        store.close()


def test_prune_base_exception_is_preserved_and_rolled_back(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "history"
    _seed_prune_store(root, (_RUN_A, _RUN_B), finalized_count=2)
    store = history._open_existing_writer(root=root)  # pyright: ignore[reportPrivateUsage]
    assert store is not None
    abort = _ClockAbort("private prune abort")

    def abort_delete(_connection: sqlite3.Connection, _run_id: str) -> sqlite3.Cursor:
        raise abort

    monkeypatch.setattr(history, "_delete_run_for_prune", abort_delete)
    try:
        with pytest.raises(_ClockAbort) as caught:
            store.prune_finalized_runs(keep=0)
        assert caught.value is abort
        assert not store._connection.in_transaction  # pyright: ignore[reportPrivateUsage]
        assert len(store.list_runs()) == 2
    finally:
        store.close()


def test_prune_busy_writer_is_bounded_and_leaves_no_partial_deletion(
    tmp_path: Path,
) -> None:
    root = tmp_path / "history"
    _seed_prune_store(root, (_RUN_A, _RUN_B), finalized_count=2)
    blocker = open_writer(root=root)
    blocker._connection.execute("BEGIN IMMEDIATE")  # pyright: ignore[reportPrivateUsage]
    expected_bounded_sqlite_waits = 2
    hosted_scheduler_margin_seconds = 0.5
    production_write_timeout_seconds = (
        history._WRITE_TIMEOUT_SECONDS  # pyright: ignore[reportPrivateUsage]
    )
    aggregate_upper_bound_seconds = (
        expected_bounded_sqlite_waits * production_write_timeout_seconds
        + hosted_scheduler_margin_seconds
    )
    started = time.monotonic()
    try:
        with pytest.raises(HistoryStoreError) as caught:
            prune_runs(root=root, keep=0)
        elapsed = time.monotonic() - started
        assert str(caught.value) == ""
        assert len(blocker.list_runs()) == 2
        assert blocker._connection.in_transaction  # pyright: ignore[reportPrivateUsage]
        # Opening the existing writer can spend one busy timeout reasserting WAL,
        # then BEGIN IMMEDIATE can spend a second. The explicit margin covers only
        # hosted-runner scheduling overhead; this remains a finite regression bound.
        assert elapsed < aggregate_upper_bound_seconds
    finally:
        blocker._connection.rollback()  # pyright: ignore[reportPrivateUsage]
        assert not blocker._connection.in_transaction  # pyright: ignore[reportPrivateUsage]
        blocker.close()
    assert prune_runs(root=root, keep=1) == 1


def test_prune_active_incomplete_run_and_reader_snapshot_are_consistent(
    tmp_path: Path,
) -> None:
    root = tmp_path / "history"
    _seed_prune_store(root, (_RUN_A, _RUN_B), finalized_count=2)
    owner = open_writer(
        root=root,
        run_id_factory=lambda: uuid.UUID(_RUN_C),
        clock=lambda: _START,
        platform="linux",
    )
    reader = open_read_only(root=root)
    assert reader is not None
    try:
        owner.create_run(
            session_id="active",
            config_fingerprint=_FINGERPRINT,
            package_version="0.2.0a1",
        )
        owner.persist_events(_RUN_C, _event_snapshot()[:1])
        reader._connection.execute("BEGIN")  # pyright: ignore[reportPrivateUsage]
        before = reader.list_runs()
        assert len(before) == 3

        assert prune_runs(root=root, keep=1) == 1
        assert len(reader.list_runs()) == 3
        reader._connection.commit()  # pyright: ignore[reportPrivateUsage]
        assert {record.run_id for record in reader.list_runs()} == {_RUN_B, _RUN_C}

        active = get_run(_RUN_C, root=root)
        assert active.result is None
        assert tuple(event.sequence for event in list_events(_RUN_C, root=root)) == (
            0,
        )
        owner.finalize_run(
            _RUN_C,
            result=RunResult.COMPLETED,
            stop_reason=StopReason.CLI_STOP,
            event_high_water_mark=0,
        )
        assert get_run(_RUN_C, root=root).result is RunResult.COMPLETED
    finally:
        reader.close()
        owner.close()


def test_prune_executes_no_vacuum_or_checkpoint(tmp_path: Path) -> None:
    root = tmp_path / "history"
    _seed_prune_store(root, (_RUN_A, _RUN_B), finalized_count=2)
    store = history._open_existing_writer(root=root)  # pyright: ignore[reportPrivateUsage]
    assert store is not None
    statements: list[str] = []
    store._connection.set_trace_callback(statements.append)  # pyright: ignore[reportPrivateUsage]
    try:
        assert store.prune_finalized_runs(keep=1) == 1
    finally:
        store.close()
    normalized = "\n".join(statements).upper()
    assert "VACUUM" not in normalized
    assert "CHECKPOINT" not in normalized


def test_list_ordering_and_limit_are_deterministic(tmp_path: Path) -> None:
    identifiers = iter((uuid.UUID(_RUN_A), uuid.UUID(_RUN_B)))
    times = iter((_START, _START))
    root = tmp_path / "history"
    store = open_writer(
        root=root,
        run_id_factory=lambda: next(identifiers),
        clock=lambda: next(times),
        platform="darwin",
    )
    try:
        for session in ("alpha", "beta"):
            store.create_run(
                session_id=session,
                config_fingerprint=_FINGERPRINT,
                package_version="0.2.0a1",
            )
    finally:
        store.close()

    assert tuple(record.run_id for record in list_runs(root=root)) == (_RUN_B, _RUN_A)
    assert tuple(record.run_id for record in list_runs(root=root, limit=1)) == (_RUN_B,)
    for invalid in (0, 101, True):
        with pytest.raises(InvalidHistoryLimitError):
            list_runs(root=root, limit=invalid)  # type: ignore[arg-type]


def test_missing_store_queries_do_not_create_files(tmp_path: Path) -> None:
    root = tmp_path / "missing"
    assert list_runs(root=root) == ()
    assert not root.exists()
    with pytest.raises(RunNotFoundError):
        get_run(_RUN_A, root=root)
    assert not root.exists()


def test_invalid_and_unknown_run_ids_are_distinct(tmp_path: Path) -> None:
    with pytest.raises(InvalidRunIdError):
        get_run("not-a-run", root=tmp_path / "missing")
    with pytest.raises(RunNotFoundError):
        get_run(_RUN_A, root=tmp_path / "missing")


def test_corrupt_and_schema_mismatched_stores_fail_closed(tmp_path: Path) -> None:
    corrupt = tmp_path / "corrupt"
    corrupt.mkdir(mode=0o700)
    database = corrupt / "history.sqlite3"
    database.write_text("not sqlite", encoding="utf-8")
    os.chmod(database, 0o600)
    corrupt_before = _snapshot(corrupt)
    with pytest.raises(HistoryStoreError):
        list_runs(root=corrupt)
    with pytest.raises(HistoryStoreError):
        list_events(_RUN_A, root=corrupt)
    with pytest.raises(HistoryStoreError):
        open_writer(root=corrupt)
    assert _snapshot(corrupt) == corrupt_before
    assert set(corrupt.iterdir()) == {database}

    mismatch = tmp_path / "mismatch"
    mismatch.mkdir(mode=0o700)
    database = mismatch / "history.sqlite3"
    connection = sqlite3.connect(database)
    connection.execute("PRAGMA user_version = 2")
    connection.close()
    os.chmod(database, 0o600)
    before = _snapshot(mismatch)
    with pytest.raises(HistoryStoreError):
        list_runs(root=mismatch)
    with pytest.raises(HistoryStoreError):
        list_events(_RUN_A, root=mismatch)
    with pytest.raises(HistoryStoreError):
        open_writer(root=mismatch)
    assert _snapshot(mismatch) == before
    assert set(mismatch.iterdir()) == {database}
    connection = sqlite3.connect(f"file:{database}?mode=ro", uri=True)
    try:
        assert connection.execute("PRAGMA journal_mode").fetchone() == ("delete",)
    finally:
        connection.close()


@pytest.mark.parametrize(
    ("object_type", "statement"),
    (
        ("table", "CREATE TABLE unexpected(value TEXT)"),
        ("view", "CREATE VIEW unexpected AS SELECT run_id FROM runs"),
        (
            "trigger",
            "CREATE TRIGGER unexpected AFTER INSERT ON runs BEGIN SELECT 1; END",
        ),
        ("index", "CREATE INDEX unexpected ON runs(session_id)"),
    ),
)
def test_unexpected_user_schema_objects_are_rejected(
    tmp_path: Path,
    object_type: str,
    statement: str,
) -> None:
    root = tmp_path / object_type
    store = open_writer(root=root)
    store.close()
    connection = sqlite3.connect(root / "history.sqlite3")
    connection.execute(statement)
    connection.commit()
    connection.close()

    with pytest.raises(HistoryStoreError):
        list_runs(root=root)
    with pytest.raises(HistoryStoreError):
        open_writer(root=root)


@pytest.mark.parametrize(
    ("name", "object_name", "original", "replacement"),
    (
        (
            "changed-column",
            "runs",
            "package_version TEXT",
            "package_release TEXT",
        ),
        (
            "weakened-constraint",
            "runs",
            "length(config_fingerprint) = 64",
            "length(config_fingerprint) >= 1",
        ),
        (
            "changed-foreign-key",
            "events",
            "ON DELETE CASCADE",
            "ON DELETE RESTRICT",
        ),
    ),
)
def test_changed_schema_structure_is_rejected(
    tmp_path: Path,
    name: str,
    object_name: str,
    original: str,
    replacement: str,
) -> None:
    root = tmp_path / name
    store = open_writer(root=root)
    store.close()
    connection = sqlite3.connect(root / "history.sqlite3")
    connection.execute("PRAGMA writable_schema = ON")
    row = connection.execute(
        "SELECT sql FROM sqlite_schema WHERE name = ?",
        (object_name,),
    ).fetchone()
    assert row is not None and isinstance(row[0], str)
    changed = row[0].replace(original, replacement)
    assert changed != row[0]
    connection.execute(
        "UPDATE sqlite_schema SET sql = ? WHERE name = ?",
        (changed, object_name),
    )
    schema_version = connection.execute("PRAGMA schema_version").fetchone()
    assert schema_version is not None
    connection.execute(f"PRAGMA schema_version = {schema_version[0] + 1}")
    connection.commit()
    connection.close()

    with pytest.raises(HistoryStoreError):
        list_runs(root=root)


def test_missing_required_ordering_index_is_rejected(tmp_path: Path) -> None:
    root = tmp_path / "missing-index"
    store = open_writer(root=root)
    store.close()
    connection = sqlite3.connect(root / "history.sqlite3")
    connection.execute("DROP INDEX runs_order")
    connection.commit()
    connection.close()

    with pytest.raises(HistoryStoreError):
        list_runs(root=root)


def test_result_and_stop_reason_pairing_is_enforced(tmp_path: Path) -> None:
    root = tmp_path / "pairing"
    store = open_writer(
        root=root,
        run_id_factory=lambda: uuid.UUID(_RUN_A),
        clock=lambda: _START,
        platform="linux",
    )
    try:
        store.create_run(
            session_id="alpha",
            config_fingerprint=_FINGERPRINT,
            package_version="0.2.0a1",
        )
        with pytest.raises(HistoryStoreError):
            store.finalize_run(
                _RUN_A,
                result=RunResult.COMPLETED,
                stop_reason=StopReason.STARTUP_FAILURE,
                event_high_water_mark=None,
            )
        store._connection.execute(  # pyright: ignore[reportPrivateUsage]
            "PRAGMA ignore_check_constraints = ON"
        )
        store._connection.execute(  # pyright: ignore[reportPrivateUsage]
            """
            UPDATE runs SET ended_at = ?, result = ?, stop_reason = ?
            WHERE run_id = ?
            """,
            (
                "2026-10-18T10:11:17.123456Z",
                RunResult.COMPLETED.value,
                StopReason.STARTUP_FAILURE.value,
                _RUN_A,
            ),
        )
        with pytest.raises(HistoryStoreError):
            store.list_runs()
    finally:
        store.close()


def test_canonical_row_validation_rejects_tampering(tmp_path: Path) -> None:
    root = tmp_path / "history"
    store = open_writer(
        root=root,
        run_id_factory=lambda: uuid.UUID(_RUN_A),
        clock=lambda: _START,
        platform="linux",
    )
    store.create_run(
        session_id="alpha",
        config_fingerprint=_FINGERPRINT,
        package_version="0.2.0a1",
    )
    store._connection.execute(  # pyright: ignore[reportPrivateUsage]
        "PRAGMA ignore_check_constraints = ON"
    )
    store._connection.execute(  # pyright: ignore[reportPrivateUsage]
        "UPDATE runs SET run_id = ?",
        ("AAAAAAAA-AAAA-4AAA-8AAA-AAAAAAAAAAAA",),
    )
    store._connection.commit()  # pyright: ignore[reportPrivateUsage]
    with pytest.raises(HistoryStoreError):
        store.list_runs()
    store.close()


def test_read_only_queries_do_not_mutate_database(tmp_path: Path) -> None:
    root = tmp_path / "history"
    store = open_writer(root=root, platform="linux")
    store.close()
    before = _snapshot(root)

    reader = open_read_only(root=root)
    assert reader is not None
    try:
        assert reader.list_runs() == ()
        assert reader._connection.execute(  # pyright: ignore[reportPrivateUsage]
            "PRAGMA query_only"
        ).fetchone() == (1,)
    finally:
        reader.close()

    assert _snapshot(root) == before


@pytest.mark.parametrize(
    ("column", "value"),
    (
        ("schema_version", 2),
        ("run_id", "AAAAAAAA-AAAA-4AAA-8AAA-AAAAAAAAAAAA"),
        ("session_id", "../private"),
        ("config_fingerprint", "A" * 64),
        ("package_version", "private version"),
        ("platform", "windows"),
        ("started_at", "not-a-timestamp"),
        ("ended_at", None),
        ("result", RunResult.RUNTIME_FAILED.value),
        ("stop_reason", StopReason.RUNTIME_FAILURE.value),
        ("event_high_water_mark", 9),
    ),
)
def test_prune_rejects_each_invalid_run_column_without_mutation(
    tmp_path: Path,
    column: str,
    value: object,
) -> None:
    root = tmp_path / column
    _seed_prune_store(root, (_RUN_A,), finalized_count=1)
    connection = sqlite3.connect(root / "history.sqlite3")
    try:
        connection.execute("PRAGMA ignore_check_constraints = ON")
        connection.execute(
            f"UPDATE runs SET {column} = ?",  # noqa: S608
            (value,),
        )
        connection.commit()
    finally:
        connection.close()
    before = _snapshot(root)

    with pytest.raises(HistoryStoreError) as caught:
        prune_runs(root=root, keep=0)

    assert str(caught.value) == ""
    assert _snapshot(root) == before


@pytest.mark.parametrize(
    ("column", "value"),
    (
        ("schema_version", 2),
        ("run_id", _RUN_B),
        ("sequence", 2),
        ("resource_identity", "unsafe\nidentity"),
        ("event_type", "unknown"),
        ("outcome", "unknown"),
        ("severity", "debug"),
        ("summary", "private\nsummary"),
        ("lifecycle_state", "unknown"),
        ("health_status", "unknown"),
        ("recorded_at", "not-a-timestamp"),
    ),
)
def test_prune_rejects_each_invalid_event_column_without_mutation(
    tmp_path: Path,
    column: str,
    value: object,
) -> None:
    root = tmp_path / column
    _seed_prune_store(root, (_RUN_A,), finalized_count=1)
    connection = sqlite3.connect(root / "history.sqlite3")
    try:
        connection.execute("PRAGMA foreign_keys = OFF")
        connection.execute("PRAGMA ignore_check_constraints = ON")
        connection.execute(
            f"UPDATE events SET {column} = ?",  # noqa: S608
            (value,),
        )
        connection.commit()
    finally:
        connection.close()
    before = _snapshot(root)

    with pytest.raises(HistoryStoreError) as caught:
        prune_runs(root=root, keep=0)

    assert str(caught.value) == ""
    assert _snapshot(root) == before


@pytest.mark.parametrize(
    "kind",
    (
        "corrupt",
        "user-version",
        "extra-table",
        "extra-view",
        "extra-trigger",
        "extra-index",
    ),
)
def test_prune_rejects_corrupt_or_mismatched_schema_without_mutation(
    tmp_path: Path,
    kind: str,
) -> None:
    root = tmp_path / kind
    if kind == "corrupt":
        root.mkdir(mode=0o700)
        database = root / "history.sqlite3"
        database.write_bytes(b"not sqlite")
        os.chmod(database, 0o600)
    else:
        _seed_prune_store(root, (_RUN_A,), finalized_count=1)
        connection = sqlite3.connect(root / "history.sqlite3")
        if kind == "user-version":
            connection.execute("PRAGMA user_version = 2")
        else:
            statements = {
                "extra-table": "CREATE TABLE unexpected(value TEXT)",
                "extra-view": "CREATE VIEW unexpected AS SELECT run_id FROM runs",
                "extra-trigger": (
                    "CREATE TRIGGER unexpected AFTER INSERT ON runs "
                    "BEGIN SELECT 1; END"
                ),
                "extra-index": "CREATE INDEX unexpected ON runs(session_id)",
            }
            connection.execute(statements[kind])
        connection.commit()
        connection.close()
    before = _snapshot(root)

    with pytest.raises(HistoryStoreError) as caught:
        prune_runs(root=root, keep=0)

    assert str(caught.value) == ""
    assert _snapshot(root) == before
    assert not (root / "history.sqlite3-wal").exists()
    assert not (root / "history.sqlite3-shm").exists()


@pytest.mark.parametrize(
    ("artifact", "variant"),
    tuple(
        (artifact, variant)
        for artifact in (
            "history.lock",
            "history.sqlite3",
            "history.sqlite3-wal",
            "history.sqlite3-shm",
        )
        for variant in ("symlink", "wrong-type", "unsafe-mode")
    ),
)
def test_prune_rejects_unsafe_artifacts_without_mutation(
    tmp_path: Path,
    artifact: str,
    variant: str,
) -> None:
    root = tmp_path / f"{artifact}-{variant}"
    _seed_prune_store(root, (_RUN_A,), finalized_count=1)
    path = root / artifact
    if path.exists() or path.is_symlink():
        path.unlink()
    if variant == "symlink":
        target = tmp_path / f"target-{artifact}-{variant}"
        target.write_bytes(b"private")
        os.chmod(target, 0o600)
        path.symlink_to(target)
    elif variant == "wrong-type":
        path.mkdir(mode=0o700)
    else:
        path.write_bytes(b"private")
        os.chmod(path, 0o644)
    before = _snapshot(root)

    with pytest.raises(UnsafeHistoryPathError):
        prune_runs(root=root, keep=0)

    assert _snapshot(root) == before


def test_prune_rejects_unsafe_root_and_foreign_ownership(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "target"
    target.mkdir(mode=0o700)
    symlink = tmp_path / "symlink"
    symlink.symlink_to(target, target_is_directory=True)
    with pytest.raises(UnsafeHistoryPathError):
        prune_runs(root=symlink, keep=0)
    assert tuple(target.iterdir()) == ()

    wrong_type = tmp_path / "file"
    wrong_type.write_bytes(b"private")
    os.chmod(wrong_type, 0o600)
    with pytest.raises(UnsafeHistoryPathError):
        prune_runs(root=wrong_type, keep=0)

    unsafe_mode = tmp_path / "unsafe-mode"
    unsafe_mode.mkdir(mode=0o755)
    with pytest.raises(UnsafeHistoryPathError):
        prune_runs(root=unsafe_mode, keep=0)

    foreign = tmp_path / "foreign"
    foreign.mkdir(mode=0o700)
    owner = foreign.stat().st_uid
    monkeypatch.setattr(history.os, "geteuid", lambda: owner + 1)
    with pytest.raises(UnsafeHistoryPathError):
        prune_runs(root=foreign, keep=0)
    assert tuple(foreign.iterdir()) == ()


@pytest.mark.parametrize(
    "artifact",
    (
        "history.lock",
        "history.sqlite3",
        "history.sqlite3-wal",
        "history.sqlite3-shm",
    ),
)
def test_prune_rejects_foreign_owned_artifact_without_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    artifact: str,
) -> None:
    root = tmp_path / artifact
    _seed_prune_store(root, (_RUN_A,), finalized_count=1)
    path = root / artifact
    if not path.exists():
        path.write_bytes(b"")
        os.chmod(path, 0o600)
    original_lstat = Path.lstat
    owner = path.lstat().st_uid

    class ForeignStat:
        def __init__(self, metadata: os.stat_result) -> None:
            self._metadata = metadata
            self.st_uid = owner + 1

        def __getattr__(self, name: str) -> object:
            return getattr(self._metadata, name)

    def foreign_lstat(candidate: Path) -> os.stat_result:
        metadata = original_lstat(candidate)
        if candidate == path:
            return cast(os.stat_result, ForeignStat(metadata))
        return metadata

    before = _snapshot(root)
    monkeypatch.setattr(Path, "lstat", foreign_lstat)
    with pytest.raises(UnsafeHistoryPathError):
        prune_runs(root=root, keep=0)
    assert _snapshot(root) == before


@pytest.mark.parametrize(
    "artifact",
    (".history.sqlite3.init", "history.sqlite3-wal", "history.sqlite3-shm"),
)
def test_prune_partial_or_init_artifact_is_fail_closed(
    tmp_path: Path,
    artifact: str,
) -> None:
    root = tmp_path / artifact
    root.mkdir(mode=0o700)
    path = root / artifact
    path.write_bytes(b"private")
    os.chmod(path, 0o600)
    before = _snapshot(root)
    with pytest.raises(HistoryStoreError):
        prune_runs(root=root, keep=0)
    assert _snapshot(root) == before


def test_prune_unknown_and_init_entries_preserve_valid_store(
    tmp_path: Path,
) -> None:
    for name, expected_error in (
        ("unknown", UnsafeHistoryPathError),
        (".history.sqlite3.init", HistoryStoreError),
    ):
        root = tmp_path / name
        _seed_prune_store(root, (_RUN_A,), finalized_count=1)
        extra = root / name
        extra.write_bytes(b"private")
        os.chmod(extra, 0o600)
        before = _snapshot(root)
        with pytest.raises(expected_error):
            prune_runs(root=root, keep=0)
        assert _snapshot(root) == before


def test_prune_existing_lock_without_database_is_missing_store_zero_mutation(
    tmp_path: Path,
) -> None:
    root = tmp_path / "history"
    root.mkdir(mode=0o700)
    lock = root / "history.lock"
    lock.write_bytes(b"")
    os.chmod(lock, 0o600)
    before = _snapshot(root)
    assert prune_runs(root=root, keep=0) == 0
    assert _snapshot(root) == before


def test_prune_existing_database_does_not_create_missing_lock(tmp_path: Path) -> None:
    root = tmp_path / "history"
    _seed_prune_store(root, (_RUN_A, _RUN_B), finalized_count=2)
    (root / "history.lock").unlink()
    assert not (root / "history.lock").exists()

    assert prune_runs(root=root, keep=1) == 1

    assert not (root / "history.lock").exists()
    assert tuple(record.run_id for record in list_runs(root=root)) == (_RUN_B,)


def _snapshot(
    directory: Path,
) -> dict[str, tuple[int, int, int, int, bytes | None]]:
    snapshot: dict[str, tuple[int, int, int, int, bytes | None]] = {}
    for entry in directory.iterdir():
        metadata = entry.lstat()
        payload = entry.read_bytes() if stat.S_ISREG(metadata.st_mode) else None
        snapshot[entry.name] = (
            metadata.st_ino,
            metadata.st_mode,
            metadata.st_size,
            metadata.st_mtime_ns,
            payload,
        )
    return snapshot
