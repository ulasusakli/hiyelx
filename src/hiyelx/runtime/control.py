"""Private Unix-socket control for one foreground local runtime process."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import signal
import stat
import sys
from collections.abc import Callable, Mapping
from contextlib import suppress
from dataclasses import dataclass
from enum import IntEnum, StrEnum
from importlib import import_module
from pathlib import Path
from types import ModuleType
from typing import Protocol, cast

from hiyelx import __version__
from hiyelx.config import RuntimeConfig
from hiyelx.models import ModelRegistry
from hiyelx.resources import (
    HealthStatus,
    LifecycleState,
    ResourceIdentity,
    ResourceOperation,
)
from hiyelx.runtime.errors import RuntimeTopologyError
from hiyelx.runtime.history import (
    HistoryError,
    HistoryStore,
    RunRecord,
    RunResult,
    StopReason,
    open_writer,
)
from hiyelx.runtime.operations import RuntimeOperations, RuntimeOperationsSnapshot
from hiyelx.runtime.planning import plan_startup
from hiyelx.runtime.state import RuntimeManagerState
from hiyelx.simulation import (
    SIMULATED_MOTOR_MODEL,
    SIMULATION_PREVIEW_SCHEMA_VERSION,
    SimulationMotorPreviewState,
    SimulationPreviewResourceSnapshot,
    SimulationPreviewSnapshot,
    SimulationPreviewUnavailableError,
    UnsupportedSimulationPreviewResourceError,
    register_simulated_motor,
)

PROTOCOL_VERSION = 1
MAX_MESSAGE_BYTES = 8192
MIN_PREVIEW_RESOURCES = 1
MAX_PREVIEW_RESOURCES = 1
PREVIEW_REQUEST_TIMEOUT_SECONDS = 3.0
STATE_DIRECTORY_ENV = "HIYELX_RUNTIME_STATE_DIR"
_MANIFEST_NAME = "manifest.json"
_MANIFEST_TEMP_NAME = ".manifest.tmp"
_LOCK_NAME = "owner.lock"
_SOCKET_NAME = "control.sock"
_REQUEST_TIMEOUT_SECONDS = 3.0
_SUPPORTED_PLATFORMS = frozenset({"darwin", "linux"})
_MAX_RESOURCE_IDENTITY_LENGTH = 64
_SANITIZED_HEALTH_SUMMARIES = frozenset(
    f"{prefix} during {operation.value}"
    for prefix in (
        "deadline exceeded",
        "backend unavailable",
        "safe-stop failed",
        "lifecycle cleanup failed",
    )
    for operation in ResourceOperation
)
_SANITIZED_EVENT_SUMMARIES = frozenset(
    {
        "motor safe-stop attempted",
        "motor safe-stop failed",
        "motor safe-stop succeeded",
        "resource health degraded after safe-stop failure",
        "resource shutdown attempted",
        "resource shutdown attempted during startup rollback",
        "resource shutdown failed",
        "resource shutdown failed during startup rollback",
        "resource shutdown succeeded",
        "resource shutdown succeeded during startup rollback",
        "resource start attempted",
        "resource start failed",
        "resource start succeeded",
        "runtime failed during shutdown",
        "runtime failed during startup",
        "runtime running",
        "runtime shutdown requested",
        "runtime start requested",
        "runtime stopped",
        "safe-stop cleanup completed",
        "safe-stop requested",
        "startup rollback attempted",
        "startup rollback completed",
    }
)


class RuntimeCliExitCode(IntEnum):
    """Stable process exit codes for Runtime Operations CLI commands."""

    SUCCESS = 0
    INVALID_CONFIGURATION = 2
    INVALID_SESSION_ID = 3
    SESSION_ALREADY_RUNNING = 4
    SESSION_NOT_RUNNING = 5
    CONTROL_PROTOCOL_FAILURE = 6
    RUNTIME_STARTUP_FAILURE = 7
    RUNTIME_CLEANUP_FAILURE = 8
    UNSUPPORTED_PLATFORM = 9
    HISTORY_STORE_FAILURE = 10
    RUN_NOT_FOUND = 11


class RuntimeControlError(Exception):
    """Base class for sanitized local-control failures."""


class UnsupportedPlatformError(RuntimeControlError):
    """Raised when Unix-domain sockets are unavailable by platform policy."""


class InvalidSessionIdError(RuntimeControlError, ValueError):
    """Raised when a session identifier cannot safely name local artifacts."""


class UnsafeSessionPathError(RuntimeControlError):
    """Raised when local control artifact ownership is ambiguous or unsafe."""


class SessionAlreadyRunningError(RuntimeControlError):
    """Raised when another process holds the session ownership lock."""


class SessionNotRunningError(RuntimeControlError):
    """Raised when no active owner exists for a session."""


class ControlProtocolError(RuntimeControlError):
    """Raised for malformed, unsafe, unavailable, or inconsistent control I/O."""


class InvalidRuntimeControlConfigurationError(RuntimeControlError):
    """Base class for a validated config outside the bounded RTO-2 contract."""


class UnsupportedRuntimeModelError(InvalidRuntimeControlConfigurationError):
    """Raised before construction when a configuration is not simulation-only."""


class UnsafeRuntimeIdentityError(InvalidRuntimeControlConfigurationError):
    """Raised when an identity cannot be rendered as one safe status field."""


class RuntimeOwnerStartupError(RuntimeControlError):
    """Raised when the foreground owner cannot construct or start its runtime."""


class RuntimeOwnerCleanupError(RuntimeControlError):
    """Raised after every available cleanup step was attempted."""


class RuntimeHistoryError(RuntimeControlError):
    """Raised for a sanitized durable run-history failure."""


class RuntimePreviewUnavailableError(RuntimeControlError):
    """Raised when the active owner cannot produce one coherent preview."""

    def __init__(self) -> None:
        super().__init__("runtime preview is unavailable")


class RuntimePreviewUnsupportedError(RuntimeControlError):
    """Raised when the active owner is outside the preview resource bound."""

    def __init__(self) -> None:
        super().__init__("runtime preview is unsupported")


class ControlCommand(StrEnum):
    """Commands supported by the private local-control protocol."""

    STATUS = "status"
    STOP = "stop"
    PREVIEW = "preview"


class ControlErrorCode(StrEnum):
    """Stable sanitized failures returned over the private protocol."""

    INVALID_REQUEST = "invalid_request"
    UNKNOWN_COMMAND = "unknown_command"
    RUNTIME_CLEANUP_FAILED = "runtime_cleanup_failed"
    RUNTIME_HISTORY_FAILED = "runtime_history_failed"
    PREVIEW_UNAVAILABLE = "preview_unavailable"
    PREVIEW_UNSUPPORTED = "preview_unsupported"
    INTERNAL_FAILURE = "internal_failure"


_CONTROL_FAILURE_MESSAGES = {
    ControlErrorCode.INVALID_REQUEST: "control request is invalid",
    ControlErrorCode.UNKNOWN_COMMAND: "control command is unknown",
    ControlErrorCode.RUNTIME_CLEANUP_FAILED: "runtime cleanup failed",
    ControlErrorCode.RUNTIME_HISTORY_FAILED: "runtime history failed",
    ControlErrorCode.PREVIEW_UNAVAILABLE: "runtime preview is unavailable",
    ControlErrorCode.PREVIEW_UNSUPPORTED: "runtime preview is unsupported",
    ControlErrorCode.INTERNAL_FAILURE: "control operation failed",
}


@dataclass(frozen=True, slots=True)
class ControlRequest:
    """One strictly validated request for one connection."""

    command: ControlCommand
    session: str


@dataclass(frozen=True, slots=True)
class ResourceStatus:
    """Wire-safe resource state derived from an RTO-1 snapshot."""

    identity: ResourceIdentity
    lifecycle_state: LifecycleState
    health_status: HealthStatus
    health_summary: str | None


@dataclass(frozen=True, slots=True)
class StatusReply:
    """Strict successful status reply."""

    session: str
    manager_state: RuntimeManagerState
    resources: tuple[ResourceStatus, ...]
    successful_start_order: tuple[ResourceIdentity, ...]
    active_resource_order: tuple[ResourceIdentity, ...]
    event_high_water_mark: int | None
    latest_event_summary: str | None


@dataclass(frozen=True, slots=True)
class StopReply:
    """Strict successful stop reply."""

    session: str


@dataclass(frozen=True, slots=True)
class PreviewReply:
    """Strict successful private preview reply."""

    session: str
    preview: SimulationPreviewSnapshot


@dataclass(frozen=True, slots=True)
class FailureReply:
    """Strict sanitized failure reply."""

    code: ControlErrorCode
    message: str


ControlReply = StatusReply | StopReply | PreviewReply | FailureReply


@dataclass(frozen=True, slots=True)
class SessionLayout:
    """Deterministic private paths for one validated session identifier."""

    root: Path
    session: str

    @property
    def directory(self) -> Path:
        return self.root / self.session

    @property
    def lock(self) -> Path:
        return self.directory / _LOCK_NAME

    @property
    def manifest(self) -> Path:
        return self.directory / _MANIFEST_NAME

    @property
    def manifest_temp(self) -> Path:
        return self.directory / _MANIFEST_TEMP_NAME

    @property
    def socket(self) -> Path:
        return self.directory / _SOCKET_NAME


@dataclass(frozen=True, slots=True)
class SessionManifest:
    """Minimal non-authoritative metadata for one published control socket."""

    session: str
    config_fingerprint: str
    owner_uid: int
    pid: int


class _FcntlProtocol(Protocol):
    LOCK_EX: int
    LOCK_NB: int
    LOCK_UN: int

    def flock(self, file_descriptor: int, operation: int) -> None: ...


class OwnedSession:
    """Exclusive lock and bounded artifacts owned by one foreground process."""

    def __init__(self, layout: SessionLayout, lock_fd: int) -> None:
        self.layout = layout
        self._lock_fd = lock_fd
        self._closed = False
        self._cleanup_result = False

    def publish(self, config_fingerprint: str) -> None:
        """Publish a strict manifest atomically after the socket is listening."""
        manifest = SessionManifest(
            session=self.layout.session,
            config_fingerprint=config_fingerprint,
            owner_uid=os.geteuid(),
            pid=os.getpid(),
        )
        _write_manifest_atomic(self.layout, manifest)

    def cleanup(self, *, final: bool = False) -> bool:
        """Remove only owned artifacts, continuing after individual failures."""
        if self._closed:
            return self._cleanup_result
        succeeded = True
        cleanup_directory = self.layout.root / f".cleanup-{self.layout.session}"
        try:
            directory_exists = _lexists(self.layout.directory)
            cleanup_exists = _lexists(cleanup_directory)
            if directory_exists == cleanup_exists:
                raise UnsafeSessionPathError
            if directory_exists:
                _preflight_session_directory(self.layout.directory)
                for path, expected_kind in (
                    (self.layout.socket, "socket"),
                    (self.layout.manifest, "file"),
                    (self.layout.manifest_temp, "file"),
                ):
                    try:
                        _unlink_owned(
                            path,
                            expected_kind=expected_kind,
                            missing_ok=True,
                        )
                    except RuntimeControlError:
                        succeeded = False
                if succeeded:
                    _preflight_lock_only_directory(self.layout.directory)
                    os.rename(self.layout.directory, cleanup_directory)
            else:
                _preflight_lock_only_directory(cleanup_directory)
            if succeeded:
                cleanup_lock = cleanup_directory / _LOCK_NAME
                _unlink_owned(cleanup_lock, expected_kind="file", missing_ok=False)
                os.rmdir(cleanup_directory)
        except (OSError, RuntimeControlError):
            succeeded = False
        if succeeded or final:
            try:
                _fcntl().flock(self._lock_fd, _fcntl().LOCK_UN)
            except OSError:
                succeeded = False
            try:
                os.close(self._lock_fd)
            except OSError:
                succeeded = False
            self._closed = True
            self._cleanup_result = succeeded
        return succeeded


class StopCoordinator:
    """Coordinate one cleanup transition across concurrent stop requests."""

    def __init__(self) -> None:
        self.requested = asyncio.Event()
        self.stop_reason: StopReason | None = None
        self._result: asyncio.Future[ControlReply] = (
            asyncio.get_running_loop().create_future()
        )

    async def request_stop(self) -> ControlReply:
        if self.stop_reason is None:
            self.stop_reason = StopReason.CLI_STOP
        self.requested.set()
        return await asyncio.shield(self._result)

    def request_local_stop(self) -> None:
        if self.stop_reason is None:
            self.stop_reason = StopReason.SIGINT
        self.requested.set()

    def complete(self, reply: ControlReply) -> None:
        if not self._result.done():
            self._result.set_result(reply)

    @property
    def completed(self) -> bool:
        return self._result.done()


class LocalControlServer:
    """One-request-per-connection private Unix-domain control server."""

    def __init__(
        self,
        layout: SessionLayout,
        operations: RuntimeOperations,
        coordinator: StopCoordinator,
    ) -> None:
        self._layout = layout
        self._operations = operations
        self._coordinator = coordinator
        self._server: asyncio.Server | None = None
        self._handlers: set[asyncio.Task[None]] = set()

    async def start(self) -> None:
        try:
            self._server = await asyncio.start_unix_server(
                self._handle_connection,
                path=str(self._layout.socket),
                limit=MAX_MESSAGE_BYTES + 1,
            )
            os.chmod(self._layout.socket, 0o600, follow_symlinks=False)
            _validate_owned_path(self._layout.socket, expected_kind="socket")
        except (OSError, RuntimeControlError) as error:
            raise ControlProtocolError from error

    def stop_accepting(self) -> None:
        if self._server is None:
            return
        self._server.close()

    async def close(self) -> None:
        if self._server is None:
            return
        self.stop_accepting()
        await self._server.wait_closed()
        self._server = None

    async def wait_handlers(self) -> None:
        if self._handlers:
            await asyncio.gather(*tuple(self._handlers), return_exceptions=True)

    async def _handle_connection(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        task = asyncio.current_task()
        if task is not None:
            self._handlers.add(cast(asyncio.Task[None], task))
        try:
            reply = await self._reply_for_connection(reader)
            try:
                encoded_reply = encode_reply(reply)
            except Exception:
                encoded_reply = encode_reply(
                    FailureReply(
                        ControlErrorCode.INTERNAL_FAILURE,
                        "control operation failed",
                    )
                )
            writer.write(encoded_reply)
            await writer.drain()
        except (ConnectionError, OSError):
            pass
        finally:
            writer.close()
            with suppress(ConnectionError, OSError):
                await writer.wait_closed()
            if task is not None:
                self._handlers.discard(cast(asyncio.Task[None], task))

    async def _reply_for_connection(self, reader: asyncio.StreamReader) -> ControlReply:
        try:
            message = await asyncio.wait_for(
                reader.readline(),
                timeout=_REQUEST_TIMEOUT_SECONDS,
            )
            request = decode_request(message)
        except UnknownControlCommandError:
            return FailureReply(
                ControlErrorCode.UNKNOWN_COMMAND,
                "control command is unknown",
            )
        except (TimeoutError, ValueError, RuntimeControlError):
            return FailureReply(
                ControlErrorCode.INVALID_REQUEST,
                "control request is invalid",
            )

        if request.session != self._layout.session:
            return FailureReply(
                ControlErrorCode.INVALID_REQUEST,
                "control request is invalid",
            )
        if request.command is ControlCommand.STATUS:
            try:
                return status_reply(self._layout.session, self._operations.snapshot())
            except Exception:
                return FailureReply(
                    ControlErrorCode.INTERNAL_FAILURE,
                    "control operation failed",
                )
        if request.command is ControlCommand.PREVIEW:
            try:
                preview = self._operations.simulation_preview_snapshot()
                _validate_preview_transport_snapshot(preview)
                return PreviewReply(self._layout.session, preview)
            except SimulationPreviewUnavailableError:
                return FailureReply(
                    ControlErrorCode.PREVIEW_UNAVAILABLE,
                    "runtime preview is unavailable",
                )
            except UnsupportedSimulationPreviewResourceError:
                return FailureReply(
                    ControlErrorCode.PREVIEW_UNSUPPORTED,
                    "runtime preview is unsupported",
                )
            except UnsupportedPreviewResourceCountError:
                return FailureReply(
                    ControlErrorCode.PREVIEW_UNSUPPORTED,
                    "runtime preview is unsupported",
                )
            except Exception:
                return FailureReply(
                    ControlErrorCode.INTERNAL_FAILURE,
                    "control operation failed",
                )
        return await self._coordinator.request_stop()


class UnknownControlCommandError(ControlProtocolError):
    """Internal distinction used to return a stable unknown-command response."""


class UnsupportedPreviewResourceCountError(ControlProtocolError):
    """Internal distinction for the one-resource cross-process Alpha bound."""


def validate_session_id(session: str) -> str:
    """Return a safe session identifier or raise before path construction."""
    if not 1 <= len(session) <= 48:
        raise InvalidSessionIdError
    if not session[0].isalnum() or not session[0].isascii():
        raise InvalidSessionIdError
    if any(
        not character.isascii()
        or not (character.islower() or character.isdigit() or character in "_-")
        for character in session
    ):
        raise InvalidSessionIdError
    return session


def resolve_state_directory(
    environment: Mapping[str, str] | None = None,
    *,
    platform: str | None = None,
) -> Path:
    """Resolve the deterministic private state root without creating it."""
    _require_supported_platform(platform)
    values = os.environ if environment is None else environment
    override = values.get(STATE_DIRECTORY_ENV)
    if override is not None:
        path = Path(override)
        if not path.is_absolute() or not override or "\x00" in override:
            raise UnsafeSessionPathError
        return path
    return Path("/tmp") / f"hiyelx-runtime-{os.geteuid()}"


def validate_simulation_config(config: RuntimeConfig) -> None:
    """Reject every non-built-in-simulation model before factory invocation."""
    if any(definition.model != SIMULATED_MOTOR_MODEL for definition in config.resources):
        raise UnsupportedRuntimeModelError
    if any(
        not _is_safe_resource_identity(definition.identity)
        for definition in config.resources
    ):
        raise UnsafeRuntimeIdentityError
    try:
        plan_startup(config)
    except RuntimeTopologyError as error:
        raise InvalidRuntimeControlConfigurationError from error


def configuration_fingerprint(config: RuntimeConfig) -> str:
    """Return a deterministic digest without retaining the raw configuration."""
    document = {
        "resources": [
            {
                "depends_on": [identity.value for identity in definition.depends_on],
                "identity": definition.identity.value,
                "model": definition.model,
                "settings": definition.settings,
            }
            for definition in config.resources
        ],
        "schema_version": config.schema_version,
    }
    try:
        encoded = json.dumps(
            document,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise UnsupportedRuntimeModelError from error
    return hashlib.sha256(encoded).hexdigest()


def reserve_session(
    session: str,
    *,
    state_directory: Path | None = None,
) -> OwnedSession:
    """Exclusively reserve a session, reclaiming only safely detected stale state."""
    validated = validate_session_id(session)
    root = state_directory or resolve_state_directory()
    _ensure_private_directory(root)
    layout = SessionLayout(root, validated)
    created_directory = False
    try:
        os.mkdir(layout.directory, 0o700)
        created_directory = True
    except FileExistsError:
        _validate_owned_path(layout.directory, expected_kind="directory")
        _preflight_session_directory(layout.directory)
    except OSError as error:
        raise UnsafeSessionPathError from error

    lock_fd = _open_lock(layout.lock, create=created_directory)
    fcntl = _fcntl()
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError as error:
        os.close(lock_fd)
        raise SessionAlreadyRunningError from error
    except OSError as error:
        os.close(lock_fd)
        raise UnsafeSessionPathError from error

    owned = OwnedSession(layout, lock_fd)
    try:
        _clear_stale_control_artifacts(layout)
    except RuntimeControlError:
        owned.cleanup(final=True)
        raise
    return owned


def status_reply(session: str, snapshot: RuntimeOperationsSnapshot) -> StatusReply:
    """Project an immutable RTO-1 snapshot into the private wire contract."""
    latest = snapshot.events[-1].summary if snapshot.events else None
    reply = StatusReply(
        session=session,
        manager_state=snapshot.manager_state,
        resources=tuple(
            ResourceStatus(
                identity=resource.identity,
                lifecycle_state=resource.lifecycle_state,
                health_status=resource.health_status,
                health_summary=resource.health_summary,
            )
            for resource in snapshot.resources
        ),
        successful_start_order=snapshot.successful_start_order,
        active_resource_order=snapshot.active_resource_order,
        event_high_water_mark=snapshot.event_high_water_mark,
        latest_event_summary=latest,
    )
    _validate_status_content(reply)
    return reply


def render_status(reply: StatusReply) -> tuple[str, ...]:
    """Render the exact deterministic script-friendly status transcript."""
    lines = [
        f"session={reply.session}",
        f"manager-state={reply.manager_state.value}",
        f"resource-count={len(reply.resources)}",
    ]
    lines.extend(
        f"resource={resource.identity.value} "
        f"lifecycle={resource.lifecycle_state.value} "
        f"health={resource.health_status.value} "
        f"health-summary={resource.health_summary or 'none'}"
        for resource in reply.resources
    )
    lines.extend(
        (
            "successful-start-order="
            + ",".join(identity.value for identity in reply.successful_start_order),
            "active-resource-order="
            + ",".join(identity.value for identity in reply.active_resource_order),
            "event-high-water-mark="
            + (
                "none"
                if reply.event_high_water_mark is None
                else str(reply.event_high_water_mark)
            ),
            "latest-event=" + (reply.latest_event_summary or "none"),
        )
    )
    return tuple(lines)


def encode_request(request: ControlRequest) -> bytes:
    """Encode one deterministic bounded request."""
    validate_session_id(request.session)
    return _encode_document(
        {
            "command": request.command.value,
            "protocol_version": PROTOCOL_VERSION,
            "session": request.session,
        }
    )


def decode_request(message: bytes) -> ControlRequest:
    """Strictly decode one bounded request."""
    document = _decode_document(message)
    _require_exact_keys(document, {"command", "protocol_version", "session"})
    version = document["protocol_version"]
    if type(version) is not int or version != PROTOCOL_VERSION:
        raise ControlProtocolError
    command_value = document["command"]
    session_value = document["session"]
    if not isinstance(command_value, str) or not isinstance(session_value, str):
        raise ControlProtocolError
    try:
        command = ControlCommand(command_value)
    except ValueError as error:
        raise UnknownControlCommandError from error
    try:
        session = validate_session_id(session_value)
    except InvalidSessionIdError as error:
        raise ControlProtocolError from error
    return ControlRequest(command, session)


def encode_reply(reply: ControlReply) -> bytes:
    """Encode one deterministic bounded response."""
    if isinstance(reply, StatusReply):
        _validate_status_content(reply)
        result: dict[str, object] = {
            "active_resource_order": [
                identity.value for identity in reply.active_resource_order
            ],
            "event_high_water_mark": reply.event_high_water_mark,
            "latest_event_summary": reply.latest_event_summary,
            "manager_state": reply.manager_state.value,
            "resources": [
                {
                    "health_status": resource.health_status.value,
                    "health_summary": resource.health_summary,
                    "identity": resource.identity.value,
                    "lifecycle_state": resource.lifecycle_state.value,
                }
                for resource in reply.resources
            ],
            "session": reply.session,
            "successful_start_order": [
                identity.value for identity in reply.successful_start_order
            ],
        }
        return _encode_document(
            {
                "kind": "status",
                "ok": True,
                "protocol_version": PROTOCOL_VERSION,
                "result": result,
            }
        )
    if isinstance(reply, StopReply):
        return _encode_document(
            {
                "kind": "stop",
                "ok": True,
                "protocol_version": PROTOCOL_VERSION,
                "result": {"session": reply.session, "stopped": True},
            }
        )
    if isinstance(reply, PreviewReply):
        validate_session_id(reply.session)
        _validate_preview_transport_snapshot(reply.preview)
        return _encode_document(
            {
                "kind": "preview",
                "ok": True,
                "protocol_version": PROTOCOL_VERSION,
                "result": {
                    "preview": _encode_preview_snapshot(reply.preview),
                    "session": reply.session,
                },
            }
        )
    return _encode_document(
        {
            "error": {"code": reply.code.value, "message": reply.message},
            "ok": False,
            "protocol_version": PROTOCOL_VERSION,
        }
    )


def decode_reply(message: bytes) -> ControlReply:
    """Strictly decode one bounded response."""
    document = _decode_document(message)
    version = document.get("protocol_version")
    if type(version) is not int or version != PROTOCOL_VERSION:
        raise ControlProtocolError
    ok = document.get("ok")
    if ok is False:
        _require_exact_keys(document, {"error", "ok", "protocol_version"})
        error = document["error"]
        if not isinstance(error, dict):
            raise ControlProtocolError
        typed_error = cast(dict[object, object], error)
        _require_exact_keys(typed_error, {"code", "message"})
        code = typed_error["code"]
        message_value = typed_error["message"]
        if not isinstance(code, str) or not isinstance(message_value, str):
            raise ControlProtocolError
        try:
            error_code = ControlErrorCode(code)
        except ValueError as error_value:
            raise ControlProtocolError from error_value
        if message_value != _CONTROL_FAILURE_MESSAGES[error_code]:
            raise ControlProtocolError
        return FailureReply(error_code, message_value)
    if ok is not True:
        raise ControlProtocolError
    _require_exact_keys(document, {"kind", "ok", "protocol_version", "result"})
    kind = document["kind"]
    result = document["result"]
    if not isinstance(kind, str) or not isinstance(result, dict):
        raise ControlProtocolError
    typed_result = cast(dict[object, object], result)
    if kind == "stop":
        _require_exact_keys(typed_result, {"session", "stopped"})
        session = typed_result["session"]
        if not isinstance(session, str) or typed_result["stopped"] is not True:
            raise ControlProtocolError
        return StopReply(validate_session_id(session))
    if kind == "status":
        return _decode_status_result(typed_result)
    if kind == "preview":
        _require_exact_keys(typed_result, {"preview", "session"})
        session = typed_result["session"]
        if not isinstance(session, str):
            raise ControlProtocolError
        try:
            validated_session = validate_session_id(session)
            preview = _decode_preview_snapshot(typed_result["preview"])
            _validate_preview_transport_snapshot(preview)
        except (ValueError, RuntimeControlError) as error:
            raise ControlProtocolError from error
        return PreviewReply(validated_session, preview)
    raise ControlProtocolError


async def request_status(
    session: str,
    *,
    state_directory: Path | None = None,
) -> StatusReply:
    reply = await _request(session, ControlCommand.STATUS, state_directory=state_directory)
    if isinstance(reply, StatusReply):
        return reply
    raise ControlProtocolError


async def request_stop(
    session: str,
    *,
    state_directory: Path | None = None,
) -> StopReply:
    reply = await _request(session, ControlCommand.STOP, state_directory=state_directory)
    if isinstance(reply, StopReply):
        return reply
    if (
        isinstance(reply, FailureReply)
        and reply.code is ControlErrorCode.RUNTIME_CLEANUP_FAILED
    ):
        raise RuntimeOwnerCleanupError
    if isinstance(reply, FailureReply) and reply.code is ControlErrorCode.RUNTIME_HISTORY_FAILED:
        raise RuntimeHistoryError
    raise ControlProtocolError


async def request_preview(
    session: str,
    *,
    state_directory: Path | None = None,
) -> PreviewReply:
    """Request one typed preview under one total monotonic I/O deadline."""
    try:
        async with asyncio.timeout(PREVIEW_REQUEST_TIMEOUT_SECONDS):
            reply = await _request(
                session,
                ControlCommand.PREVIEW,
                state_directory=state_directory,
            )
    except TimeoutError as error:
        raise ControlProtocolError from error
    if isinstance(reply, PreviewReply):
        return reply
    if isinstance(reply, FailureReply):
        if reply.code is ControlErrorCode.PREVIEW_UNAVAILABLE:
            raise RuntimePreviewUnavailableError
        if reply.code is ControlErrorCode.PREVIEW_UNSUPPORTED:
            raise RuntimePreviewUnsupportedError
    raise ControlProtocolError


async def run_local_runtime(
    config: RuntimeConfig,
    session: str,
    *,
    state_directory: Path | None = None,
    history_directory: Path | None = None,
    ready: Callable[[str], None] | None = None,
) -> None:
    """Own one foreground simulation runtime until explicit stop or Ctrl-C."""
    _require_supported_platform()
    validated_session = validate_session_id(session)
    validate_simulation_config(config)
    fingerprint = configuration_fingerprint(config)
    owned = reserve_session(validated_session, state_directory=state_directory)
    history_store: HistoryStore | None = None
    run_record: RunRecord | None = None
    finalization_attempted = False
    operations: RuntimeOperations | None = None
    control_server: LocalControlServer | None = None
    coordinator = StopCoordinator()
    runtime_cleaned = False
    session_cleaned = False
    signal_installed = False
    ready_published = False
    cleanup_succeeded: bool | None = None
    event_history_succeeded = True
    persisted_event_high_water_mark: int | None = None
    loop = asyncio.get_running_loop()

    def persist_event_delta() -> None:
        nonlocal event_history_succeeded, persisted_event_high_water_mark
        if (
            not event_history_succeeded
            or history_store is None
            or run_record is None
            or operations is None
        ):
            return
        try:
            snapshot = operations.snapshot()
            persisted_event_high_water_mark = history_store.persist_events(
                run_record.run_id,
                snapshot.events,
            )
        except Exception:
            event_history_succeeded = False

    try:
        try:
            try:
                history_store = open_writer(root=history_directory)
                run_record = history_store.create_run(
                    session_id=validated_session,
                    config_fingerprint=fingerprint,
                    package_version=__version__,
                )
            except HistoryError as error:
                raise RuntimeHistoryError from error

            registry = ModelRegistry()
            register_simulated_motor(registry)
            try:
                operations = RuntimeOperations(config, registry)
                try:
                    await operations.start()
                except Exception:
                    persist_event_delta()
                    raise
                persist_event_delta()
                if not event_history_succeeded:
                    raise RuntimeHistoryError
                control_server = LocalControlServer(owned.layout, operations, coordinator)
                await control_server.start()
                try:
                    loop.add_signal_handler(signal.SIGINT, coordinator.request_local_stop)
                    signal_installed = True
                except (NotImplementedError, RuntimeError) as error:
                    raise UnsupportedPlatformError from error
                owned.publish(fingerprint)
                if ready is not None:
                    ready(validated_session)
            except (RuntimeHistoryError, UnsupportedPlatformError):
                raise
            except Exception as error:
                raise RuntimeOwnerStartupError from error
            ready_published = True

            await coordinator.requested.wait()
            control_server.stop_accepting()
            runtime_succeeded = await _cleanup_operations(
                operations,
                persist_events=persist_event_delta,
            )
            runtime_cleaned = True
            session_succeeded = owned.cleanup()
            session_cleaned = session_succeeded
            cleanup_succeeded = runtime_succeeded and session_succeeded
            finalization_attempted = True
            history_succeeded = _finalize_run_history(
                history_store,
                run_record,
                result=(
                    RunResult.CLEANUP_FAILED
                    if not cleanup_succeeded
                    else RunResult.HISTORY_FAILED
                    if not event_history_succeeded
                    else RunResult.COMPLETED
                    if coordinator.stop_reason is StopReason.CLI_STOP
                    else RunResult.INTERRUPTED
                    if coordinator.stop_reason is StopReason.SIGINT
                    else RunResult.RUNTIME_FAILED
                ),
                stop_reason=(
                    StopReason.CLEANUP_FAILURE
                    if not cleanup_succeeded
                    else StopReason.HISTORY_FAILURE
                    if not event_history_succeeded
                    else coordinator.stop_reason or StopReason.RUNTIME_FAILURE
                ),
                event_high_water_mark=persisted_event_high_water_mark,
            )
            if cleanup_succeeded and event_history_succeeded and history_succeeded:
                coordinator.complete(StopReply(validated_session))
            elif cleanup_succeeded and (
                not event_history_succeeded or not history_succeeded
            ):
                coordinator.complete(
                    FailureReply(
                        ControlErrorCode.RUNTIME_HISTORY_FAILED,
                        "runtime history failed",
                    )
                )
            else:
                coordinator.complete(
                    FailureReply(
                        ControlErrorCode.RUNTIME_CLEANUP_FAILED,
                        "runtime cleanup failed",
                    )
                )
            await control_server.wait_handlers()
            await control_server.close()
            if not cleanup_succeeded:
                raise RuntimeOwnerCleanupError
            if not event_history_succeeded or not history_succeeded:
                raise RuntimeHistoryError
        finally:
            active_error = sys.exc_info()[1]
            cleanup_interruption: BaseException | None = None
            final_cleanup_succeeded = (
                True if cleanup_succeeded is None else cleanup_succeeded
            )
            if signal_installed:
                try:
                    loop.remove_signal_handler(signal.SIGINT)
                except BaseException as error:
                    final_cleanup_succeeded = False
                    cleanup_interruption = error
            if operations is not None and not runtime_cleaned:
                try:
                    final_cleanup_succeeded = await _cleanup_operations(
                        operations,
                        persist_events=persist_event_delta,
                    )
                except BaseException as error:
                    final_cleanup_succeeded = False
                    cleanup_interruption = error
            if control_server is not None:
                try:
                    control_server.stop_accepting()
                except BaseException as error:
                    final_cleanup_succeeded = False
                    if cleanup_interruption is None:
                        cleanup_interruption = error
            if not coordinator.completed:
                try:
                    coordinator.complete(
                        FailureReply(
                            ControlErrorCode.RUNTIME_CLEANUP_FAILED,
                            "runtime cleanup failed",
                        )
                    )
                except BaseException as error:
                    final_cleanup_succeeded = False
                    if cleanup_interruption is None:
                        cleanup_interruption = error
            if control_server is not None:
                try:
                    await control_server.wait_handlers()
                    await control_server.close()
                except BaseException as error:
                    final_cleanup_succeeded = False
                    if cleanup_interruption is None:
                        cleanup_interruption = error
            if not session_cleaned:
                try:
                    final_cleanup_succeeded = (
                        owned.cleanup(final=True) and final_cleanup_succeeded
                    )
                except BaseException as error:
                    final_cleanup_succeeded = False
                    if cleanup_interruption is None:
                        cleanup_interruption = error
            if (
                history_store is not None
                and run_record is not None
                and not finalization_attempted
            ):
                if not ready_published and not isinstance(
                    active_error,
                    RuntimeHistoryError,
                ):
                    result = RunResult.STARTUP_FAILED
                    reason = StopReason.STARTUP_FAILURE
                elif not final_cleanup_succeeded:
                    result = RunResult.CLEANUP_FAILED
                    reason = StopReason.CLEANUP_FAILURE
                elif active_error is not None and not isinstance(
                    active_error,
                    RuntimeHistoryError,
                ):
                    result = RunResult.RUNTIME_FAILED
                    reason = StopReason.RUNTIME_FAILURE
                elif not event_history_succeeded or isinstance(
                    active_error,
                    RuntimeHistoryError,
                ):
                    result = RunResult.HISTORY_FAILED
                    reason = StopReason.HISTORY_FAILURE
                else:
                    result = None
                    reason = None
                if result is not None and reason is not None:
                    finalization_attempted = True
                    _finalize_run_history(
                        history_store,
                        run_record,
                        result=result,
                        stop_reason=reason,
                        event_high_water_mark=persisted_event_high_water_mark,
                    )
            if cleanup_interruption is not None and active_error is None:
                raise cleanup_interruption
            if not final_cleanup_succeeded and isinstance(active_error, RuntimeHistoryError):
                raise RuntimeOwnerCleanupError from active_error
            if not final_cleanup_succeeded and active_error is None:
                raise RuntimeOwnerCleanupError
    finally:
        if history_store is not None:
            history_store.close()


def _finalize_run_history(
    store: HistoryStore,
    record: RunRecord,
    *,
    result: RunResult,
    stop_reason: StopReason,
    event_high_water_mark: int | None,
) -> bool:
    try:
        store.finalize_run(
            record.run_id,
            result=result,
            stop_reason=stop_reason,
            event_high_water_mark=event_high_water_mark,
        )
    except HistoryError:
        return False
    return True


async def _cleanup_operations(
    operations: RuntimeOperations,
    *,
    persist_events: Callable[[], None] | None = None,
) -> bool:
    succeeded = True
    if operations.snapshot().manager_state is RuntimeManagerState.RUNNING:
        try:
            await operations.safe_stop()
        except Exception:
            succeeded = False
        finally:
            if persist_events is not None:
                persist_events()
        if operations.snapshot().manager_state is RuntimeManagerState.RUNNING:
            try:
                await operations.shutdown()
            except Exception:
                succeeded = False
            finally:
                if persist_events is not None:
                    persist_events()
    return succeeded


async def _request(
    session: str,
    command: ControlCommand,
    *,
    state_directory: Path | None,
) -> ControlReply:
    _require_supported_platform()
    validated_session = validate_session_id(session)
    root = state_directory or resolve_state_directory()
    layout = _locate_active_session(root, validated_session)
    reader: asyncio.StreamReader
    writer: asyncio.StreamWriter
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_unix_connection(str(layout.socket), limit=MAX_MESSAGE_BYTES + 1),
            timeout=_REQUEST_TIMEOUT_SECONDS,
        )
    except (TimeoutError, ConnectionError, OSError) as error:
        if not _lexists(layout.directory):
            raise SessionNotRunningError from error
        raise ControlProtocolError from error
    try:
        writer.write(encode_request(ControlRequest(command, validated_session)))
        await writer.drain()
        message = await asyncio.wait_for(
            reader.readline(),
            timeout=_REQUEST_TIMEOUT_SECONDS,
        )
        return decode_reply(message)
    except (TimeoutError, ConnectionError, OSError, ValueError) as error:
        raise ControlProtocolError from error
    finally:
        writer.close()
        with suppress(ConnectionError, OSError):
            await writer.wait_closed()


def _encode_preview_snapshot(snapshot: SimulationPreviewSnapshot) -> dict[str, object]:
    return {
        "resources": [
            {
                "health_status": resource.health_status.value,
                "health_summary": resource.health_summary,
                "identity": resource.identity.value,
                "kind": resource.kind,
                "lifecycle_state": resource.lifecycle_state.value,
                "state": {
                    "angular_position_radians": (
                        resource.state.angular_position_radians
                    ),
                    "angular_velocity_radians_per_second": (
                        resource.state.angular_velocity_radians_per_second
                    ),
                    "revision": resource.state.revision,
                    "simulation_time_seconds": (
                        resource.state.simulation_time_seconds
                    ),
                },
            }
            for resource in snapshot.resources
        ],
        "runtime_state": snapshot.runtime_state.value,
        "schema_version": snapshot.schema_version,
    }


def _decode_preview_snapshot(value: object) -> SimulationPreviewSnapshot:
    if not isinstance(value, dict):
        raise ControlProtocolError
    document = cast(dict[object, object], value)
    _require_exact_keys(document, {"resources", "runtime_state", "schema_version"})
    schema_version = document["schema_version"]
    runtime_state = document["runtime_state"]
    resources = document["resources"]
    if (
        type(schema_version) is not str
        or schema_version != SIMULATION_PREVIEW_SCHEMA_VERSION
        or not isinstance(runtime_state, str)
        or not isinstance(resources, list)
    ):
        raise ControlProtocolError
    try:
        snapshot = SimulationPreviewSnapshot(
            schema_version=SIMULATION_PREVIEW_SCHEMA_VERSION,
            runtime_state=RuntimeManagerState(runtime_state),
            resources=tuple(
                _decode_preview_resource(item)
                for item in cast(list[object], resources)
            ),
        )
        _validate_preview_transport_snapshot(snapshot)
        return snapshot
    except (TypeError, ValueError, RuntimeControlError) as error:
        raise ControlProtocolError from error


def _decode_preview_resource(value: object) -> SimulationPreviewResourceSnapshot:
    if not isinstance(value, dict):
        raise ControlProtocolError
    resource = cast(dict[object, object], value)
    _require_exact_keys(
        resource,
        {
            "health_status",
            "health_summary",
            "identity",
            "kind",
            "lifecycle_state",
            "state",
        },
    )
    identity = resource["identity"]
    kind = resource["kind"]
    lifecycle_state = resource["lifecycle_state"]
    health_status = resource["health_status"]
    health_summary = resource["health_summary"]
    if (
        not isinstance(identity, str)
        or type(kind) is not str
        or kind != "motor"
        or not isinstance(lifecycle_state, str)
        or not isinstance(health_status, str)
        or (health_summary is not None and not isinstance(health_summary, str))
    ):
        raise ControlProtocolError
    try:
        return SimulationPreviewResourceSnapshot(
            identity=ResourceIdentity(identity),
            kind="motor",
            lifecycle_state=LifecycleState(lifecycle_state),
            health_status=HealthStatus(health_status),
            health_summary=health_summary,
            state=_decode_preview_motor_state(resource["state"]),
        )
    except (TypeError, ValueError) as error:
        raise ControlProtocolError from error


def _decode_preview_motor_state(value: object) -> SimulationMotorPreviewState:
    if not isinstance(value, dict):
        raise ControlProtocolError
    state = cast(dict[object, object], value)
    _require_exact_keys(
        state,
        {
            "angular_position_radians",
            "angular_velocity_radians_per_second",
            "revision",
            "simulation_time_seconds",
        },
    )
    position = state["angular_position_radians"]
    velocity = state["angular_velocity_radians_per_second"]
    revision = state["revision"]
    simulation_time = state["simulation_time_seconds"]
    if (
        type(position) is not float
        or type(velocity) is not float
        or type(revision) is not int
        or type(simulation_time) is not float
    ):
        raise ControlProtocolError
    try:
        return SimulationMotorPreviewState(
            angular_position_radians=position,
            angular_velocity_radians_per_second=velocity,
            simulation_time_seconds=simulation_time,
            revision=revision,
        )
    except ValueError as error:
        raise ControlProtocolError from error


def _validate_preview_transport_snapshot(snapshot: SimulationPreviewSnapshot) -> None:
    if not MIN_PREVIEW_RESOURCES <= len(snapshot.resources) <= MAX_PREVIEW_RESOURCES:
        raise UnsupportedPreviewResourceCountError


def _decode_status_result(result: dict[object, object]) -> StatusReply:
    _require_exact_keys(
        result,
        {
            "active_resource_order",
            "event_high_water_mark",
            "latest_event_summary",
            "manager_state",
            "resources",
            "session",
            "successful_start_order",
        },
    )
    session = result["session"]
    manager_state = result["manager_state"]
    resources = result["resources"]
    successful = result["successful_start_order"]
    active = result["active_resource_order"]
    high_water = result["event_high_water_mark"]
    latest = result["latest_event_summary"]
    if (
        not isinstance(session, str)
        or not isinstance(manager_state, str)
        or not isinstance(resources, list)
        or not isinstance(successful, list)
        or not isinstance(active, list)
        or (
            high_water is not None
            and (isinstance(high_water, bool) or not isinstance(high_water, int))
        )
        or (latest is not None and not isinstance(latest, str))
    ):
        raise ControlProtocolError
    try:
        reply = StatusReply(
            session=validate_session_id(session),
            manager_state=RuntimeManagerState(manager_state),
            resources=tuple(
                _decode_resource_status(value) for value in cast(list[object], resources)
            ),
            successful_start_order=_decode_identity_list(cast(list[object], successful)),
            active_resource_order=_decode_identity_list(cast(list[object], active)),
            event_high_water_mark=high_water,
            latest_event_summary=latest,
        )
        _validate_status_content(reply)
        return reply
    except (ValueError, TypeError) as error:
        raise ControlProtocolError from error


def _decode_resource_status(value: object) -> ResourceStatus:
    if not isinstance(value, dict):
        raise ControlProtocolError
    resource = cast(dict[object, object], value)
    _require_exact_keys(
        resource,
        {"health_status", "health_summary", "identity", "lifecycle_state"},
    )
    identity = resource["identity"]
    lifecycle = resource["lifecycle_state"]
    health = resource["health_status"]
    summary = resource["health_summary"]
    if (
        not isinstance(identity, str)
        or not isinstance(lifecycle, str)
        or not isinstance(health, str)
        or (summary is not None and not isinstance(summary, str))
    ):
        raise ControlProtocolError
    return ResourceStatus(
        ResourceIdentity(identity),
        LifecycleState(lifecycle),
        HealthStatus(health),
        summary,
    )


def _validate_status_content(reply: StatusReply) -> None:
    if any(
        not _is_safe_resource_identity(resource.identity)
        or (
            resource.health_summary is not None
            and resource.health_summary not in _SANITIZED_HEALTH_SUMMARIES
        )
        for resource in reply.resources
    ):
        raise ControlProtocolError
    if any(
        not _is_safe_resource_identity(identity)
        for identity in (*reply.successful_start_order, *reply.active_resource_order)
    ):
        raise ControlProtocolError
    if (
        reply.latest_event_summary is not None
        and reply.latest_event_summary not in _SANITIZED_EVENT_SUMMARIES
    ):
        raise ControlProtocolError


def _is_safe_resource_identity(identity: ResourceIdentity) -> bool:
    value = identity.value
    return (
        1 <= len(value) <= _MAX_RESOURCE_IDENTITY_LENGTH
        and value[0].isascii()
        and (value[0].islower() or value[0].isdigit())
        and all(
            character.isascii()
            and (
                character.islower()
                or character.isdigit()
                or character in "_-"
            )
            for character in value
        )
    )


def _decode_identity_list(value: list[object]) -> tuple[ResourceIdentity, ...]:
    if any(not isinstance(item, str) for item in value):
        raise ControlProtocolError
    return tuple(ResourceIdentity(cast(str, item)) for item in value)


def _encode_document(document: Mapping[str, object]) -> bytes:
    encoded = (
        json.dumps(document, ensure_ascii=True, separators=(",", ":"), sort_keys=True)
        + "\n"
    ).encode("utf-8")
    if len(encoded) > MAX_MESSAGE_BYTES:
        raise ControlProtocolError
    return encoded


def _decode_document(message: bytes) -> dict[object, object]:
    if not message or len(message) > MAX_MESSAGE_BYTES or not message.endswith(b"\n"):
        raise ControlProtocolError
    try:
        document = cast(
            object,
            json.loads(
                message.decode("utf-8"),
                object_pairs_hook=_reject_duplicate_object_keys,
            ),
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ControlProtocolError from error
    if not isinstance(document, dict):
        raise ControlProtocolError
    return cast(dict[object, object], document)


def _reject_duplicate_object_keys(
    pairs: list[tuple[str, object]],
) -> dict[str, object]:
    document: dict[str, object] = {}
    for key, value in pairs:
        if key in document:
            raise ControlProtocolError
        document[key] = value
    return document


def _require_exact_keys(document: Mapping[object, object], expected: set[str]) -> None:
    if set(document) != expected:
        raise ControlProtocolError


def _require_supported_platform(platform: str | None = None) -> None:
    current = sys.platform if platform is None else platform
    if current not in _SUPPORTED_PLATFORMS or not hasattr(asyncio, "start_unix_server"):
        raise UnsupportedPlatformError


def _ensure_private_directory(path: Path) -> None:
    try:
        os.mkdir(path, 0o700)
    except FileExistsError:
        _validate_owned_path(path, expected_kind="directory")
    except OSError as error:
        raise UnsafeSessionPathError from error
    _validate_owned_path(path, expected_kind="directory")


def _validate_owned_path(path: Path, *, expected_kind: str) -> os.stat_result:
    try:
        status = os.lstat(path)
    except OSError as error:
        raise UnsafeSessionPathError from error
    kind_matches = {
        "directory": stat.S_ISDIR(status.st_mode),
        "file": stat.S_ISREG(status.st_mode),
        "socket": stat.S_ISSOCK(status.st_mode),
    }[expected_kind]
    if (
        not kind_matches
        or status.st_uid != os.geteuid()
        or stat.S_IMODE(status.st_mode) & 0o077
    ):
        raise UnsafeSessionPathError
    return status


def _open_lock(path: Path, *, create: bool) -> int:
    flags = os.O_RDWR | getattr(os, "O_NOFOLLOW", 0)
    if create:
        flags |= os.O_CREAT
    try:
        file_descriptor = os.open(path, flags, 0o600)
    except OSError as error:
        raise UnsafeSessionPathError from error
    try:
        status = os.fstat(file_descriptor)
        if (
            not stat.S_ISREG(status.st_mode)
            or status.st_uid != os.geteuid()
            or stat.S_IMODE(status.st_mode) & 0o077
        ):
            raise UnsafeSessionPathError
    except Exception:
        os.close(file_descriptor)
        raise
    return file_descriptor


def _clear_stale_control_artifacts(layout: SessionLayout) -> None:
    _preflight_session_directory(layout.directory)
    for path, expected_kind in (
        (layout.socket, "socket"),
        (layout.manifest, "file"),
        (layout.manifest_temp, "file"),
    ):
        _unlink_owned(path, expected_kind=expected_kind, missing_ok=True)
    _preflight_lock_only_directory(layout.directory)


def _preflight_session_directory(directory: Path) -> None:
    _preflight_directory_entries(
        directory,
        {
            _LOCK_NAME: "file",
            _MANIFEST_NAME: "file",
            _MANIFEST_TEMP_NAME: "file",
            _SOCKET_NAME: "socket",
        },
    )


def _preflight_lock_only_directory(directory: Path) -> None:
    _preflight_directory_entries(directory, {_LOCK_NAME: "file"})


def _preflight_directory_entries(
    directory: Path,
    expected: Mapping[str, str],
) -> None:
    _validate_owned_path(directory, expected_kind="directory")
    try:
        entries = tuple(directory.iterdir())
    except OSError as error:
        raise UnsafeSessionPathError from error
    by_name = {entry.name: entry for entry in entries}
    if _LOCK_NAME not in by_name or not set(by_name).issubset(expected):
        raise UnsafeSessionPathError
    for name, entry in by_name.items():
        _validate_owned_path(entry, expected_kind=expected[name])


def _write_manifest_atomic(layout: SessionLayout, manifest: SessionManifest) -> None:
    document = {
        "config_fingerprint": manifest.config_fingerprint,
        "owner_uid": manifest.owner_uid,
        "pid": manifest.pid,
        "protocol_version": PROTOCOL_VERSION,
        "session": manifest.session,
    }
    encoded = json.dumps(
        document,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    try:
        file_descriptor = os.open(layout.manifest_temp, flags, 0o600)
        try:
            remaining = memoryview(encoded)
            while remaining:
                written = os.write(file_descriptor, remaining)
                if written == 0:
                    raise OSError
                remaining = remaining[written:]
            os.fsync(file_descriptor)
        finally:
            os.close(file_descriptor)
        if _lexists(layout.manifest):
            raise UnsafeSessionPathError
        os.replace(layout.manifest_temp, layout.manifest)
        _validate_owned_path(layout.manifest, expected_kind="file")
    except (OSError, RuntimeControlError) as error:
        with suppress(RuntimeControlError):
            _unlink_owned(layout.manifest_temp, expected_kind="file", missing_ok=True)
        raise UnsafeSessionPathError from error


def _read_manifest(layout: SessionLayout) -> SessionManifest:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        file_descriptor = os.open(layout.manifest, flags)
        try:
            status = os.fstat(file_descriptor)
            if (
                not stat.S_ISREG(status.st_mode)
                or status.st_uid != os.geteuid()
                or stat.S_IMODE(status.st_mode) & 0o077
            ):
                raise UnsafeSessionPathError
            encoded = os.read(file_descriptor, MAX_MESSAGE_BYTES + 1)
        finally:
            os.close(file_descriptor)
        if len(encoded) > MAX_MESSAGE_BYTES:
            raise UnsafeSessionPathError
        document = cast(object, json.loads(encoded.decode("utf-8")))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise UnsafeSessionPathError from error
    if not isinstance(document, dict):
        raise UnsafeSessionPathError
    values = cast(dict[object, object], document)
    if set(values) != {
        "config_fingerprint",
        "owner_uid",
        "pid",
        "protocol_version",
        "session",
    }:
        raise UnsafeSessionPathError
    fingerprint = values["config_fingerprint"]
    owner_uid = values["owner_uid"]
    pid = values["pid"]
    session = values["session"]
    if (
        values["protocol_version"] != PROTOCOL_VERSION
        or not isinstance(fingerprint, str)
        or len(fingerprint) != 64
        or any(character not in "0123456789abcdef" for character in fingerprint)
        or isinstance(owner_uid, bool)
        or not isinstance(owner_uid, int)
        or owner_uid != os.geteuid()
        or isinstance(pid, bool)
        or not isinstance(pid, int)
        or pid <= 0
        or not isinstance(session, str)
        or session != layout.session
    ):
        raise UnsafeSessionPathError
    return SessionManifest(session, fingerprint, owner_uid, pid)


def _locate_active_session(root: Path, session: str) -> SessionLayout:
    if not _lexists(root):
        raise SessionNotRunningError
    _validate_owned_path(root, expected_kind="directory")
    layout = SessionLayout(root, session)
    if not _lexists(layout.directory):
        raise SessionNotRunningError
    _validate_owned_path(layout.directory, expected_kind="directory")
    if not _lexists(layout.lock):
        raise UnsafeSessionPathError
    lock_fd = _open_lock(layout.lock, create=False)
    fcntl = _fcntl()
    try:
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            pass
        else:
            stale = OwnedSession(layout, lock_fd)
            if not stale.cleanup(final=True):
                raise UnsafeSessionPathError
            raise SessionNotRunningError
    finally:
        with suppress(OSError):
            os.close(lock_fd)
    _read_manifest(layout)
    _validate_owned_path(layout.socket, expected_kind="socket")
    return layout


def _unlink_owned(path: Path, *, expected_kind: str, missing_ok: bool) -> None:
    if not _lexists(path):
        if missing_ok:
            return
        raise UnsafeSessionPathError
    _validate_owned_path(path, expected_kind=expected_kind)
    try:
        os.unlink(path)
    except OSError as error:
        raise UnsafeSessionPathError from error


def _lexists(path: Path) -> bool:
    try:
        os.lstat(path)
    except FileNotFoundError:
        return False
    except OSError as error:
        raise UnsafeSessionPathError from error
    return True


def _fcntl() -> _FcntlProtocol:
    try:
        module: ModuleType = import_module("fcntl")
    except ImportError as error:
        raise UnsupportedPlatformError from error
    return cast(_FcntlProtocol, module)
