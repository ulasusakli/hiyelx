"""Private durable run history for the local runtime owner."""

from __future__ import annotations

import fcntl
import os
import re
import sqlite3
import stat
import sys
import time
import uuid
from collections.abc import Callable, Mapping
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import cast
from urllib.parse import quote

HISTORY_DIRECTORY_ENV = "HIYELX_RUNTIME_HISTORY_DIR"
SCHEMA_VERSION = 1
DEFAULT_LIMIT = 20
MAX_LIMIT = 100
_WRITE_TIMEOUT_SECONDS = 1.0
_WRITE_TIMEOUT_MILLISECONDS = 1000
_INITIALIZATION_LOCK_TIMEOUT_SECONDS = 1.0
_LOCK_POLL_INTERVAL_SECONDS = 0.01

_LOCK_NAME = "history.lock"
_DATABASE_NAME = "history.sqlite3"
_WAL_NAME = "history.sqlite3-wal"
_SHM_NAME = "history.sqlite3-shm"
_INITIAL_DATABASE_NAME = ".history.sqlite3.init"
_ALLOWED_ENTRIES = frozenset(
    {_LOCK_NAME, _DATABASE_NAME, _WAL_NAME, _SHM_NAME, _INITIAL_DATABASE_NAME}
)
_SUPPORTED_PLATFORMS = frozenset({"darwin", "linux"})
_FINGERPRINT = re.compile(r"[0-9a-f]{64}\Z")
_TIMESTAMP = re.compile(
    r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}Z\Z"
)


class HistoryError(Exception):
    """Base class for sanitized durable-history failures."""


class UnsafeHistoryPathError(HistoryError):
    """Raised when durable artifacts cannot be trusted without mutation."""


class HistoryStoreError(HistoryError):
    """Raised when the store is corrupt, incompatible, or unavailable."""


class InvalidHistoryLimitError(HistoryError, ValueError):
    """Raised when a query limit is outside the public CLI range."""


class InvalidRunIdError(HistoryError, ValueError):
    """Raised when a run ID is not a canonical lowercase UUID4."""


class RunNotFoundError(HistoryError):
    """Raised when a canonical run ID does not exist."""


class RunAlreadyFinalizedError(HistoryError):
    """Raised when a run has already reached a terminal result."""


class RunResult(StrEnum):
    COMPLETED = "completed"
    STARTUP_FAILED = "startup_failed"
    RUNTIME_FAILED = "runtime_failed"
    CLEANUP_FAILED = "cleanup_failed"
    INTERRUPTED = "interrupted"
    HISTORY_FAILED = "history_failed"


class StopReason(StrEnum):
    CLI_STOP = "cli_stop"
    SIGINT = "sigint"
    STARTUP_FAILURE = "startup_failure"
    RUNTIME_FAILURE = "runtime_failure"
    CLEANUP_FAILURE = "cleanup_failure"
    HISTORY_FAILURE = "history_failure"


_RESULT_STOP_REASONS = {
    RunResult.COMPLETED: StopReason.CLI_STOP,
    RunResult.INTERRUPTED: StopReason.SIGINT,
    RunResult.STARTUP_FAILED: StopReason.STARTUP_FAILURE,
    RunResult.RUNTIME_FAILED: StopReason.RUNTIME_FAILURE,
    RunResult.CLEANUP_FAILED: StopReason.CLEANUP_FAILURE,
    RunResult.HISTORY_FAILED: StopReason.HISTORY_FAILURE,
}

_RUNS_TABLE_SQL = """\
CREATE TABLE runs (
    schema_version INTEGER NOT NULL CHECK (schema_version = 1),
    run_id TEXT PRIMARY KEY NOT NULL CHECK (
        length(run_id) = 36
        AND run_id = lower(run_id)
        AND substr(run_id, 9, 1) = '-'
        AND substr(run_id, 14, 1) = '-'
        AND substr(run_id, 15, 1) = '4'
        AND substr(run_id, 19, 1) = '-'
        AND substr(run_id, 20, 1) IN ('8', '9', 'a', 'b')
        AND substr(run_id, 24, 1) = '-'
        AND run_id NOT GLOB '*[^0-9a-f-]*'
    ),
    session_id TEXT NOT NULL CHECK (
        length(session_id) BETWEEN 1 AND 48
        AND substr(session_id, 1, 1) GLOB '[a-z0-9]'
        AND session_id NOT GLOB '*[^a-z0-9_-]*'
    ),
    config_fingerprint TEXT NOT NULL CHECK (
        length(config_fingerprint) = 64
        AND config_fingerprint NOT GLOB '*[^0-9a-f]*'
    ),
    package_version TEXT NOT NULL CHECK (length(package_version) BETWEEN 1 AND 32),
    platform TEXT NOT NULL CHECK (platform IN ('darwin', 'linux')),
    started_at TEXT NOT NULL CHECK (length(started_at) = 27),
    ended_at TEXT CHECK (ended_at IS NULL OR length(ended_at) = 27),
    result TEXT CHECK (result IS NULL OR result IN (
        'completed', 'startup_failed', 'runtime_failed',
        'cleanup_failed', 'interrupted', 'history_failed'
    )),
    stop_reason TEXT CHECK (stop_reason IS NULL OR stop_reason IN (
        'cli_stop', 'sigint', 'startup_failure', 'runtime_failure',
        'cleanup_failure', 'history_failure'
    )),
    event_high_water_mark INTEGER CHECK (
        event_high_water_mark IS NULL OR event_high_water_mark >= 0
    ),
    CHECK (
        (ended_at IS NULL AND result IS NULL AND stop_reason IS NULL)
        OR
        (ended_at IS NOT NULL AND result IS NOT NULL AND stop_reason IS NOT NULL)
    ),
    CHECK (
        result IS NULL
        OR (result = 'completed' AND stop_reason = 'cli_stop')
        OR (result = 'interrupted' AND stop_reason = 'sigint')
        OR (result = 'startup_failed' AND stop_reason = 'startup_failure')
        OR (result = 'runtime_failed' AND stop_reason = 'runtime_failure')
        OR (result = 'cleanup_failed' AND stop_reason = 'cleanup_failure')
        OR (result = 'history_failed' AND stop_reason = 'history_failure')
    )
)"""

_RUNS_INDEX_SQL = """\
CREATE INDEX runs_order ON runs(started_at DESC, run_id DESC)"""

_EVENTS_TABLE_SQL = """\
CREATE TABLE events (
    schema_version INTEGER NOT NULL CHECK (schema_version = 1),
    run_id TEXT NOT NULL,
    sequence INTEGER NOT NULL CHECK (sequence >= 0),
    resource_identity TEXT,
    event_type TEXT NOT NULL CHECK (length(event_type) BETWEEN 1 AND 64),
    outcome TEXT NOT NULL CHECK (outcome IN (
        'requested', 'attempted', 'succeeded', 'failed', 'completed'
    )),
    severity TEXT NOT NULL CHECK (severity IN ('info', 'warning', 'error')),
    summary TEXT NOT NULL CHECK (length(summary) BETWEEN 1 AND 256),
    lifecycle_state TEXT,
    health_status TEXT,
    recorded_at TEXT NOT NULL CHECK (length(recorded_at) = 27),
    PRIMARY KEY (run_id, sequence),
    FOREIGN KEY (run_id) REFERENCES runs(run_id) ON DELETE CASCADE
)"""

_EXPECTED_USER_OBJECTS = {
    ("table", "runs", "runs"),
    ("table", "events", "events"),
    ("index", "runs_order", "runs"),
}
_EXPECTED_RUN_COLUMNS = (
    (0, "schema_version", "INTEGER", 1, None, 0),
    (1, "run_id", "TEXT", 1, None, 1),
    (2, "session_id", "TEXT", 1, None, 0),
    (3, "config_fingerprint", "TEXT", 1, None, 0),
    (4, "package_version", "TEXT", 1, None, 0),
    (5, "platform", "TEXT", 1, None, 0),
    (6, "started_at", "TEXT", 1, None, 0),
    (7, "ended_at", "TEXT", 0, None, 0),
    (8, "result", "TEXT", 0, None, 0),
    (9, "stop_reason", "TEXT", 0, None, 0),
    (10, "event_high_water_mark", "INTEGER", 0, None, 0),
)
_EXPECTED_EVENT_COLUMNS = (
    (0, "schema_version", "INTEGER", 1, None, 0),
    (1, "run_id", "TEXT", 1, None, 1),
    (2, "sequence", "INTEGER", 1, None, 2),
    (3, "resource_identity", "TEXT", 0, None, 0),
    (4, "event_type", "TEXT", 1, None, 0),
    (5, "outcome", "TEXT", 1, None, 0),
    (6, "severity", "TEXT", 1, None, 0),
    (7, "summary", "TEXT", 1, None, 0),
    (8, "lifecycle_state", "TEXT", 0, None, 0),
    (9, "health_status", "TEXT", 0, None, 0),
    (10, "recorded_at", "TEXT", 1, None, 0),
)


@dataclass(frozen=True, slots=True)
class RunRecord:
    schema_version: int
    run_id: str
    session_id: str
    config_fingerprint: str
    package_version: str
    platform: str
    started_at: str
    ended_at: str | None
    result: RunResult | None
    stop_reason: StopReason | None
    event_high_water_mark: int | None


class HistoryStore:
    """One validated SQLite reader or short-transaction writer connection."""

    def __init__(
        self,
        connection: sqlite3.Connection,
        *,
        writable: bool,
        run_id_factory: Callable[[], uuid.UUID | str] = uuid.uuid4,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        platform: str | None = None,
    ) -> None:
        self._connection = connection
        self._writable = writable
        self._run_id_factory = run_id_factory
        self._clock = clock
        self._platform = sys.platform if platform is None else platform
        self._closed = False

    def create_run(
        self,
        *,
        session_id: str,
        config_fingerprint: str,
        package_version: str,
    ) -> RunRecord:
        """Create one incomplete run before runtime construction begins."""
        if not self._writable or self._closed:
            raise HistoryStoreError
        try:
            run_id = validate_run_id(str(self._run_id_factory()))
            started_at = _format_timestamp(self._clock())
            _validate_session_id(session_id)
            _validate_fingerprint(config_fingerprint)
            _validate_package_version(package_version)
            _validate_platform(self._platform)
        except HistoryError:
            raise
        except Exception as error:
            raise HistoryStoreError from error
        record = RunRecord(
            SCHEMA_VERSION,
            run_id,
            session_id,
            config_fingerprint,
            package_version,
            self._platform,
            started_at,
            None,
            None,
            None,
            None,
        )
        try:
            self._connection.execute("BEGIN IMMEDIATE")
            self._connection.execute(
                """
                INSERT INTO runs (
                    schema_version, run_id, session_id, config_fingerprint,
                    package_version, platform, started_at, ended_at, result,
                    stop_reason, event_high_water_mark
                ) VALUES (?, ?, ?, ?, ?, ?, ?, NULL, NULL, NULL, NULL)
                """,
                (
                    record.schema_version,
                    record.run_id,
                    record.session_id,
                    record.config_fingerprint,
                    record.package_version,
                    record.platform,
                    record.started_at,
                ),
            )
            self._connection.commit()
        except sqlite3.Error as error:
            with suppress(sqlite3.Error):
                self._connection.rollback()
            raise HistoryStoreError from error
        return record

    def finalize_run(
        self,
        run_id: str,
        *,
        result: RunResult,
        stop_reason: StopReason,
        event_high_water_mark: int | None,
    ) -> RunRecord:
        """Finalize exactly one previously incomplete run."""
        if not self._writable or self._closed:
            raise HistoryStoreError
        validated_id = validate_run_id(run_id)
        if _RESULT_STOP_REASONS.get(result) is not stop_reason:
            raise HistoryStoreError
        if event_high_water_mark is not None and (
            type(event_high_water_mark) is not int or event_high_water_mark < 0
        ):
            raise HistoryStoreError
        try:
            self._connection.execute("BEGIN IMMEDIATE")
            existing = self._connection.execute(
                "SELECT ended_at FROM runs WHERE run_id = ?",
                (validated_id,),
            ).fetchone()
            if existing is None:
                raise RunNotFoundError
            if existing[0] is not None:
                raise RunAlreadyFinalizedError
            ended_at = _format_timestamp(self._clock())
            cursor = self._connection.execute(
                """
                UPDATE runs
                SET ended_at = ?, result = ?, stop_reason = ?,
                    event_high_water_mark = ?
                WHERE run_id = ? AND ended_at IS NULL AND result IS NULL
                      AND stop_reason IS NULL
                """,
                (
                    ended_at,
                    result.value,
                    stop_reason.value,
                    event_high_water_mark,
                    validated_id,
                ),
            )
            if cursor.rowcount != 1:
                raise RunAlreadyFinalizedError
            self._connection.commit()
        except HistoryError:
            with suppress(sqlite3.Error):
                self._connection.rollback()
            raise
        except sqlite3.Error as error:
            with suppress(sqlite3.Error):
                self._connection.rollback()
            raise HistoryStoreError from error
        return self.get_run(validated_id)

    def list_runs(self, *, limit: int = DEFAULT_LIMIT) -> tuple[RunRecord, ...]:
        validated_limit = validate_limit(limit)
        try:
            rows = self._connection.execute(
                """
                SELECT schema_version, run_id, session_id, config_fingerprint,
                       package_version, platform, started_at, ended_at, result,
                       stop_reason, event_high_water_mark
                FROM runs ORDER BY started_at DESC, run_id DESC LIMIT ?
                """,
                (validated_limit,),
            ).fetchall()
        except sqlite3.Error as error:
            raise HistoryStoreError from error
        return tuple(_decode_run(row) for row in rows)

    def get_run(self, run_id: str) -> RunRecord:
        validated_id = validate_run_id(run_id)
        try:
            row = self._connection.execute(
                """
                SELECT schema_version, run_id, session_id, config_fingerprint,
                       package_version, platform, started_at, ended_at, result,
                       stop_reason, event_high_water_mark
                FROM runs WHERE run_id = ?
                """,
                (validated_id,),
            ).fetchone()
        except sqlite3.Error as error:
            raise HistoryStoreError from error
        if row is None:
            raise RunNotFoundError
        return _decode_run(row)

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        with suppress(sqlite3.Error):
            self._connection.close()

    def __enter__(self) -> HistoryStore:
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()


def resolve_history_root(environment: Mapping[str, str] | None = None) -> Path:
    """Resolve the durable history root without creating it."""
    values = os.environ if environment is None else environment
    override = values.get(HISTORY_DIRECTORY_ENV)
    if override is not None:
        path = Path(override)
        if not override or "\x00" in override or not path.is_absolute():
            raise UnsafeHistoryPathError
        return path
    xdg = values.get("XDG_STATE_HOME")
    if xdg:
        base = Path(xdg)
        if not base.is_absolute() or "\x00" in xdg:
            raise UnsafeHistoryPathError
        return base / "hiyelx" / "runtime-history"
    home = values.get("HOME")
    if not home:
        raise UnsafeHistoryPathError
    base = Path(home)
    if not base.is_absolute() or "\x00" in home:
        raise UnsafeHistoryPathError
    return base / ".local" / "state" / "hiyelx" / "runtime-history"


def open_writer(
    *,
    root: Path | None = None,
    run_id_factory: Callable[[], uuid.UUID | str] = uuid.uuid4,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    platform: str | None = None,
) -> HistoryStore:
    """Initialize and open one bounded-transaction schema-v1 writer."""
    history_root = resolve_history_root() if root is None else _absolute_root(root)
    current_platform = sys.platform if platform is None else platform
    _validate_platform(current_platform)
    _ensure_root(history_root)
    _preflight(history_root)
    _validate_artifact_set(history_root)
    database = history_root / _DATABASE_NAME
    initial_identity = (
        _validate_existing_database(history_root, database)
        if _lexists(database)
        else None
    )
    lock_fd: int | None = None
    connection: sqlite3.Connection | None = None
    created_temporary = False
    try:
        lock_fd = _open_lock(history_root / _LOCK_NAME)
        _acquire_initialization_lock(lock_fd)
        _preflight(history_root)
        _validate_artifact_set(history_root)
        if _lexists(history_root / _INITIAL_DATABASE_NAME):
            raise HistoryStoreError
        if _lexists(database):
            if (
                initial_identity is not None
                and _database_identity(database) != initial_identity
            ):
                raise HistoryStoreError
            _validate_existing_database(history_root, database)
        else:
            if initial_identity is not None:
                raise HistoryStoreError
            if any(
                _lexists(history_root / name) for name in (_WAL_NAME, _SHM_NAME)
            ):
                raise HistoryStoreError
            temporary = history_root / _INITIAL_DATABASE_NAME
            _create_database(temporary)
            created_temporary = True
            _fsync_file(temporary)
            os.replace(temporary, database)
            created_temporary = False
            _fsync_directory(history_root)
        connection = _connect_writer(database)
        _validate_schema(connection)
        _preflight(history_root)
        store = HistoryStore(
            connection,
            writable=True,
            run_id_factory=run_id_factory,
            clock=clock,
            platform=current_platform,
        )
        connection = None
        return store
    except Exception as error:
        if connection is not None:
            connection.close()
        if created_temporary:
            with suppress(OSError):
                os.unlink(history_root / _INITIAL_DATABASE_NAME)
        if isinstance(error, HistoryError):
            raise
        raise HistoryStoreError from error
    finally:
        if lock_fd is not None:
            with suppress(OSError):
                fcntl.flock(lock_fd, fcntl.LOCK_UN)
            with suppress(OSError):
                os.close(lock_fd)


def open_read_only(*, root: Path | None = None) -> HistoryStore | None:
    """Open an existing store without creating or mutating any artifact."""
    history_root = resolve_history_root() if root is None else _absolute_root(root)
    if not _lexists(history_root):
        return None
    _preflight(history_root)
    _validate_artifact_set(history_root)
    database = history_root / _DATABASE_NAME
    if not _lexists(database):
        if any(
            _lexists(history_root / name)
            for name in (_INITIAL_DATABASE_NAME, _WAL_NAME, _SHM_NAME)
        ):
            raise HistoryStoreError
        return None
    connection = _connect_read_only(history_root, database)
    try:
        _validate_schema(connection)
        return HistoryStore(connection, writable=False)
    except Exception:
        connection.close()
        raise


def list_runs(*, root: Path | None = None, limit: int = DEFAULT_LIMIT) -> tuple[RunRecord, ...]:
    validate_limit(limit)
    store = open_read_only(root=root)
    if store is None:
        return ()
    try:
        return store.list_runs(limit=limit)
    finally:
        store.close()


def get_run(run_id: str, *, root: Path | None = None) -> RunRecord:
    validated_id = validate_run_id(run_id)
    store = open_read_only(root=root)
    if store is None:
        raise RunNotFoundError
    try:
        return store.get_run(validated_id)
    finally:
        store.close()


def validate_limit(limit: int) -> int:
    if type(limit) is not int or not 1 <= limit <= MAX_LIMIT:
        raise InvalidHistoryLimitError
    return limit


def validate_run_id(run_id: object) -> str:
    if not isinstance(run_id, str):
        raise InvalidRunIdError
    try:
        parsed = uuid.UUID(run_id)
    except (ValueError, AttributeError) as error:
        raise InvalidRunIdError from error
    if parsed.version != 4 or str(parsed) != run_id:
        raise InvalidRunIdError
    return run_id


def _create_database(path: Path) -> None:
    flags = os.O_RDWR | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(path, flags, 0o600)
    os.close(descriptor)
    connection: sqlite3.Connection | None = None
    try:
        connection = sqlite3.connect(path)
        connection.execute("PRAGMA journal_mode = OFF")
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA synchronous = FULL")
        connection.executescript(
            f"""
            BEGIN IMMEDIATE;
            {_RUNS_TABLE_SQL};
            {_RUNS_INDEX_SQL};
            {_EVENTS_TABLE_SQL};
            PRAGMA user_version = {SCHEMA_VERSION};
            COMMIT;
            """
        )
    except Exception:
        if connection is not None:
            connection.close()
        with suppress(OSError):
            os.unlink(path)
        raise
    else:
        connection.close()


def _connect_writer(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(
        path,
        timeout=_WRITE_TIMEOUT_SECONDS,
        isolation_level=None,
    )
    try:
        connection.execute(f"PRAGMA busy_timeout = {_WRITE_TIMEOUT_MILLISECONDS}")
        journal_mode = connection.execute("PRAGMA journal_mode = WAL").fetchone()
        if journal_mode is None or str(journal_mode[0]).lower() != "wal":
            raise HistoryStoreError
        connection.execute("PRAGMA synchronous = FULL")
        connection.execute("PRAGMA foreign_keys = ON")
        synchronous = connection.execute("PRAGMA synchronous").fetchone()
        foreign_keys = connection.execute("PRAGMA foreign_keys").fetchone()
        busy_timeout = connection.execute("PRAGMA busy_timeout").fetchone()
        if (
            synchronous != (2,)
            or foreign_keys != (1,)
            or busy_timeout != (_WRITE_TIMEOUT_MILLISECONDS,)
        ):
            raise HistoryStoreError
        return connection
    except Exception:
        connection.close()
        raise


def _connect_read_only(root: Path, database: Path) -> sqlite3.Connection:
    parameters = "mode=ro"
    if not _lexists(root / _WAL_NAME) and not _lexists(root / _SHM_NAME):
        parameters += "&immutable=1"
    uri = f"file:{quote(str(database), safe='/')}?{parameters}"
    connection: sqlite3.Connection | None = None
    try:
        connection = sqlite3.connect(uri, uri=True, timeout=0)
        connection.execute("PRAGMA query_only = ON")
        connection.execute("PRAGMA foreign_keys = ON")
        return connection
    except Exception as error:
        if connection is not None:
            connection.close()
        raise HistoryStoreError from error


def _validate_existing_database(root: Path, database: Path) -> tuple[int, ...]:
    identity = _database_identity(database)
    connection = _connect_read_only(root, database)
    try:
        _validate_schema(connection)
    finally:
        connection.close()
    return identity


def _validate_schema(connection: sqlite3.Connection) -> None:
    try:
        version = connection.execute("PRAGMA user_version").fetchone()
        objects = {
            (row[0], row[1], row[2])
            for row in connection.execute(
                """
                SELECT type, name, tbl_name FROM sqlite_schema
                WHERE type IN ('table', 'index', 'view', 'trigger')
                  AND name NOT LIKE 'sqlite_%'
                """
            ).fetchall()
        }
        schema_sql = {
            row[0]: row[1]
            for row in connection.execute(
                """
                SELECT name, sql FROM sqlite_schema
                WHERE name IN ('runs', 'events', 'runs_order')
                """
            ).fetchall()
        }
        run_columns = tuple(
            connection.execute("PRAGMA table_info(runs)").fetchall()
        )
        event_columns = tuple(
            connection.execute("PRAGMA table_info(events)").fetchall()
        )
        run_indexes = tuple(
            row
            for row in connection.execute("PRAGMA index_list(runs)").fetchall()
            if row[3] == "c"
        )
        event_indexes = tuple(
            row
            for row in connection.execute("PRAGMA index_list(events)").fetchall()
            if row[3] == "c"
        )
        ordering_columns = tuple(
            (row[2], row[3], row[4])
            for row in connection.execute("PRAGMA index_xinfo(runs_order)").fetchall()
            if row[5] == 1
        )
        integrity = connection.execute("PRAGMA quick_check").fetchall()
        run_foreign_keys = tuple(
            connection.execute("PRAGMA foreign_key_list(runs)").fetchall()
        )
        event_foreign_keys = tuple(
            connection.execute("PRAGMA foreign_key_list(events)").fetchall()
        )
    except sqlite3.Error as error:
        raise HistoryStoreError from error
    if version != (SCHEMA_VERSION,) or objects != _EXPECTED_USER_OBJECTS:
        raise HistoryStoreError
    if integrity != [("ok",)]:
        raise HistoryStoreError
    if run_columns != _EXPECTED_RUN_COLUMNS or event_columns != _EXPECTED_EVENT_COLUMNS:
        raise HistoryStoreError
    if run_indexes != ((0, "runs_order", 0, "c", 0),) or event_indexes:
        raise HistoryStoreError
    if ordering_columns != (("started_at", 1, "BINARY"), ("run_id", 1, "BINARY")):
        raise HistoryStoreError
    if run_foreign_keys or event_foreign_keys != (
        (0, 0, "runs", "run_id", "run_id", "NO ACTION", "CASCADE", "NONE"),
    ):
        raise HistoryStoreError
    expected_sql = {
        "runs": _RUNS_TABLE_SQL,
        "events": _EVENTS_TABLE_SQL,
        "runs_order": _RUNS_INDEX_SQL,
    }
    if set(schema_sql) != set(expected_sql) or any(
        not isinstance(schema_sql[name], str)
        or _normalize_schema_sql(schema_sql[name]) != _normalize_schema_sql(sql)
        for name, sql in expected_sql.items()
    ):
        raise HistoryStoreError


def _normalize_schema_sql(value: str) -> str:
    return " ".join(value.rstrip(";").split())


def _database_identity(path: Path) -> tuple[int, ...]:
    try:
        metadata = path.lstat()
    except OSError as error:
        raise UnsafeHistoryPathError from error
    if (
        not stat.S_ISREG(metadata.st_mode)
        or metadata.st_uid != os.geteuid()
        or stat.S_IMODE(metadata.st_mode) != 0o600
    ):
        raise UnsafeHistoryPathError
    return (
        metadata.st_dev,
        metadata.st_ino,
        metadata.st_uid,
        metadata.st_mode,
    )


def _ensure_root(root: Path) -> None:
    if _lexists(root):
        _validate_path(root, expected="directory", mode=0o700)
        return
    try:
        root.parent.mkdir(parents=True, exist_ok=True)
        os.mkdir(root, 0o700)
    except FileExistsError:
        pass
    except OSError as error:
        raise UnsafeHistoryPathError from error
    _validate_path(root, expected="directory", mode=0o700)


def _preflight(root: Path) -> None:
    _validate_path(root, expected="directory", mode=0o700)
    try:
        entries = tuple(root.iterdir())
    except OSError as error:
        raise UnsafeHistoryPathError from error
    if any(entry.name not in _ALLOWED_ENTRIES for entry in entries):
        raise UnsafeHistoryPathError
    for entry in entries:
        _validate_path(entry, expected="file", mode=0o600)


def _validate_artifact_set(root: Path) -> None:
    database_exists = _lexists(root / _DATABASE_NAME)
    temporary_exists = _lexists(root / _INITIAL_DATABASE_NAME)
    sidecar_exists = _lexists(root / _WAL_NAME) or _lexists(root / _SHM_NAME)
    if temporary_exists or (sidecar_exists and not database_exists):
        raise HistoryStoreError


def _open_lock(path: Path) -> int:
    flags = os.O_RDWR | os.O_CREAT
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor: int | None = None
    try:
        descriptor = os.open(path, flags, 0o600)
        _validate_descriptor(descriptor, 0o600)
        return descriptor
    except (OSError, UnsafeHistoryPathError) as error:
        if descriptor is not None:
            with suppress(OSError):
                os.close(descriptor)
        raise UnsafeHistoryPathError from error


def _acquire_initialization_lock(descriptor: int) -> None:
    deadline = time.monotonic() + _INITIALIZATION_LOCK_TIMEOUT_SECONDS
    while True:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return
        except BlockingIOError as error:
            if time.monotonic() >= deadline:
                raise HistoryStoreError from error
            time.sleep(
                min(_LOCK_POLL_INTERVAL_SECONDS, max(0.0, deadline - time.monotonic()))
            )
        except OSError as error:
            raise HistoryStoreError from error


def _validate_path(path: Path, *, expected: str, mode: int) -> None:
    try:
        metadata = path.lstat()
    except OSError as error:
        raise UnsafeHistoryPathError from error
    kind_matches = (
        stat.S_ISDIR(metadata.st_mode)
        if expected == "directory"
        else stat.S_ISREG(metadata.st_mode)
    )
    if (
        not kind_matches
        or metadata.st_uid != os.geteuid()
        or stat.S_IMODE(metadata.st_mode) != mode
    ):
        raise UnsafeHistoryPathError


def _validate_descriptor(descriptor: int, mode: int) -> None:
    metadata = os.fstat(descriptor)
    if (
        not stat.S_ISREG(metadata.st_mode)
        or metadata.st_uid != os.geteuid()
        or stat.S_IMODE(metadata.st_mode) != mode
    ):
        raise UnsafeHistoryPathError


def _decode_run(row: tuple[object, ...]) -> RunRecord:
    if len(row) != 11 or type(row[0]) is not int or row[0] != SCHEMA_VERSION:
        raise HistoryStoreError
    (
        _, run_id, session, fingerprint, version, platform, started, ended,
        result, reason, high_water,
    ) = row
    required_strings = (run_id, session, fingerprint, version, platform, started)
    if not all(isinstance(value, str) for value in required_strings):
        raise HistoryStoreError
    typed_run_id = cast(str, run_id)
    typed_session = cast(str, session)
    typed_fingerprint = cast(str, fingerprint)
    typed_version = cast(str, version)
    typed_platform = cast(str, platform)
    typed_started = cast(str, started)
    try:
        validate_run_id(typed_run_id)
        _validate_session_id(typed_session)
        _validate_fingerprint(typed_fingerprint)
        _validate_package_version(typed_version)
        _validate_platform(typed_platform)
        _validate_timestamp(typed_started)
        if ended is not None:
            if not isinstance(ended, str):
                raise HistoryStoreError
            _validate_timestamp(ended)
        typed_result = None if result is None else RunResult(result)
        typed_reason = None if reason is None else StopReason(reason)
    except (ValueError, TypeError, HistoryError) as error:
        raise HistoryStoreError from error
    if (ended is None) != (typed_result is None) or (ended is None) != (typed_reason is None):
        raise HistoryStoreError
    if typed_result is not None and _RESULT_STOP_REASONS.get(typed_result) is not typed_reason:
        raise HistoryStoreError
    if high_water is not None and (type(high_water) is not int or high_water < 0):
        raise HistoryStoreError
    return RunRecord(
        SCHEMA_VERSION,
        typed_run_id,
        typed_session,
        typed_fingerprint,
        typed_version,
        typed_platform,
        typed_started,
        ended,
        typed_result,
        typed_reason,
        high_water,
    )


def _format_timestamp(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise HistoryStoreError
    return value.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _validate_timestamp(value: object) -> None:
    if not isinstance(value, str) or not _TIMESTAMP.fullmatch(value):
        raise HistoryStoreError
    try:
        parsed = datetime.fromisoformat(value.removesuffix("Z") + "+00:00")
    except ValueError as error:
        raise HistoryStoreError from error
    if _format_timestamp(parsed) != value:
        raise HistoryStoreError


def _validate_session_id(value: object) -> None:
    if not isinstance(value, str) or not 1 <= len(value) <= 48:
        raise HistoryStoreError
    if not value[0].isascii() or not value[0].isalnum():
        raise HistoryStoreError
    if any(
        not character.isascii()
        or not (
            character.islower() or character.isdigit() or character in "_-"
        )
        for character in value
    ):
        raise HistoryStoreError


def _validate_fingerprint(value: object) -> None:
    if not isinstance(value, str) or _FINGERPRINT.fullmatch(value) is None:
        raise HistoryStoreError


def _validate_package_version(value: object) -> None:
    if (
        not isinstance(value, str)
        or not 1 <= len(value) <= 32
        or not value.isascii()
        or any(character.isspace() for character in value)
    ):
        raise HistoryStoreError


def _validate_platform(value: object) -> None:
    if value not in _SUPPORTED_PLATFORMS:
        raise HistoryStoreError


def _absolute_root(root: Path) -> Path:
    if not root.is_absolute():
        raise UnsafeHistoryPathError
    return root


def _fsync_file(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _lexists(path: Path) -> bool:
    return os.path.lexists(path)
