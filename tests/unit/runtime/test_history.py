import fcntl
import os
import sqlite3
import stat
import subprocess
import sys
import time
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

import hiyelx.runtime.history as history
from hiyelx.runtime.history import (
    HISTORY_DIRECTORY_ENV,
    HistoryStoreError,
    InvalidHistoryLimitError,
    InvalidRunIdError,
    RunAlreadyFinalizedError,
    RunNotFoundError,
    RunResult,
    StopReason,
    UnsafeHistoryPathError,
    get_run,
    list_runs,
    open_read_only,
    open_writer,
    resolve_history_root,
)

_RUN_A = "11111111-1111-4111-8111-111111111111"
_RUN_B = "22222222-2222-4222-8222-222222222222"
_START = datetime(2026, 10, 18, 10, 11, 12, 123456, tzinfo=UTC)
_FINGERPRINT = "a" * 64


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
    finally:
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

    assert all(process.returncode == 0 for process in processes)
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
            event_high_water_mark=3,
        )
        assert finalized.ended_at == "2026-10-18T10:11:17.123456Z"
        assert finalized.result is RunResult.COMPLETED
        assert finalized.stop_reason is StopReason.CLI_STOP
        assert finalized.event_high_water_mark == 3
        with pytest.raises(RunAlreadyFinalizedError):
            store.finalize_run(
                _RUN_A,
                result=RunResult.INTERRUPTED,
                stop_reason=StopReason.SIGINT,
                event_high_water_mark=None,
            )
    finally:
        store.close()


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


def _snapshot(directory: Path) -> dict[str, tuple[int, int, int, int]]:
    return {
        entry.name: (
            entry.lstat().st_ino,
            entry.lstat().st_mode,
            entry.lstat().st_size,
            entry.lstat().st_mtime_ns,
        )
        for entry in directory.iterdir()
    }
