"""Strict local HTTP host for the read-only Studio application boundary."""

from __future__ import annotations

import asyncio
import json
import os
import re
import secrets
import socket
import stat
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from hiyelx import __version__
from hiyelx.simulation import SimulationPreviewSnapshot, render_simulation_preview_json
from hiyelx.studio.application import (
    RuntimeModelSummary,
    StudioApplicationError,
    StudioErrorCode,
    StudioRuntimeInfo,
    get_preview,
    get_runtime_info,
    list_sessions,
)

HOST_VERSION = "1"
STUDIO_SCHEMA_VERSION = "1"
MAX_REQUEST_LINE_BYTES = 2_048
MAX_HEADER_LINE_BYTES = 4_096
MAX_REQUEST_HEAD_BYTES = 16_384
MAX_HEADER_FIELDS = 64
MAX_API_RESPONSE_BYTES = 32_768
MAX_STATIC_RESPONSE_BYTES = 65_536
REQUEST_READ_TIMEOUT_SECONDS = 3.0
APPLICATION_TIMEOUT_SECONDS = 4.0
LIFECYCLE_TIMEOUT_SECONDS = 3.0
CAPABILITY_HEADER = "X-HIYELX-Studio-Capability"

_LOOPBACK_HOST = "127.0.0.1"
_CAPABILITY_HEADER_KEY = CAPABILITY_HEADER.lower()
_TOKEN_PATTERN = re.compile(r"^[A-Za-z0-9_-]{43}$")
_SESSION_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]{0,47}$")
_HEADER_NAME_PATTERN = re.compile(r"^[!#$%&'*+.^_`|~0-9A-Za-z-]+$")
_STATIC_ROUTES: Mapping[str, tuple[str, str]] = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/studio.css": ("studio.css", "text/css; charset=utf-8"),
    "/fixtures.js": ("fixtures.js", "text/javascript; charset=utf-8"),
    "/app.js": ("app.js", "text/javascript; charset=utf-8"),
    "/host-client.js": ("host-client.js", "text/javascript; charset=utf-8"),
    "/live": ("live.html", "text/html; charset=utf-8"),
    "/live-app.js": ("live-app.js", "text/javascript; charset=utf-8"),
}
_STATUS_REASONS = {
    200: "OK",
    400: "Bad Request",
    403: "Forbidden",
    404: "Not Found",
    405: "Method Not Allowed",
    413: "Content Too Large",
    421: "Misdirected Request",
    422: "Unprocessable Content",
    500: "Internal Server Error",
    503: "Service Unavailable",
}
_ERRORS = {
    "invalid_request": (400, "Studio request is invalid."),
    "request_rejected": (403, "Studio request was rejected."),
    "not_found": (404, "Studio resource was not found."),
    "session_not_running": (404, "The selected session is not running."),
    "method_not_allowed": (405, "Studio request method is not allowed."),
    "request_too_large": (413, "Studio request is too large."),
    "host_rejected": (421, "Studio request was rejected."),
    "preview_unsupported": (
        422,
        "This Studio version cannot read this preview schema.",
    ),
    "application_error": (500, "Studio could not read this snapshot."),
    "sessions_unavailable": (503, "Studio could not list local sessions."),
    "preview_unavailable": (503, "Studio preview is temporarily unavailable."),
}
_APPLICATION_ERROR_CODES = {
    StudioErrorCode.INVALID_REQUEST: "invalid_request",
    StudioErrorCode.SESSIONS_UNAVAILABLE: "sessions_unavailable",
    StudioErrorCode.SESSION_NOT_RUNNING: "session_not_running",
    StudioErrorCode.PREVIEW_UNAVAILABLE: "preview_unavailable",
    StudioErrorCode.PREVIEW_UNSUPPORTED: "preview_unsupported",
    StudioErrorCode.APPLICATION_ERROR: "application_error",
}
_SECURITY_HEADERS = (
    ("Cache-Control", "no-store, max-age=0"),
    (
        "Content-Security-Policy",
        "default-src 'self'; base-uri 'none'; connect-src 'self'; "
        "form-action 'none'; frame-ancestors 'none'; img-src 'self'; "
        "object-src 'none'; script-src 'self'; style-src 'self'",
    ),
    ("Cross-Origin-Opener-Policy", "same-origin"),
    ("Cross-Origin-Resource-Policy", "same-origin"),
    (
        "Permissions-Policy",
        "camera=(), geolocation=(), microphone=(), serial=(), usb=()",
    ),
    ("Referrer-Policy", "no-referrer"),
    ("X-Content-Type-Options", "nosniff"),
    ("X-Frame-Options", "DENY"),
)

SessionLister = Callable[[], Awaitable[tuple[str, ...]]]
PreviewReader = Callable[[str], Awaitable[SimulationPreviewSnapshot]]
RuntimeInfoReader = Callable[[], Awaitable[StudioRuntimeInfo]]


class StudioHostError(Exception):
    """Base class for fixed, non-sensitive host lifecycle failures."""


class StudioHostConfigurationError(StudioHostError):
    """Raised when the injected static asset root is unsafe."""

    def __init__(self) -> None:
        super().__init__("Studio asset root is invalid.")


class StudioHostLifecycleError(StudioHostError):
    """Raised when the bounded host lifecycle cannot complete."""

    def __init__(self) -> None:
        super().__init__("Studio host lifecycle failed.")


@dataclass(frozen=True, slots=True)
class _Request:
    method: str
    target: str
    headers: Mapping[str, tuple[str, ...]]


@dataclass(frozen=True, slots=True)
class _Response:
    status: int
    content_type: str
    body: bytes
    extra_headers: tuple[tuple[str, str], ...] = ()


class _RequestInvalid(Exception):
    pass


class _RequestTooLarge(Exception):
    pass


class _StaticNotFound(Exception):
    pass


class _ResponseTooLarge(Exception):
    pass


class StudioHost:
    """One bounded IPv4 loopback host with no Runtime lifecycle authority."""

    def __init__(
        self,
        asset_root: Path,
        *,
        list_sessions_fn: SessionLister | None = None,
        get_preview_fn: PreviewReader | None = None,
        get_runtime_info_fn: RuntimeInfoReader | None = None,
    ) -> None:
        self._asset_root = _validate_asset_root(asset_root)
        self._list_sessions = list_sessions if list_sessions_fn is None else list_sessions_fn
        self._get_preview = get_preview if get_preview_fn is None else get_preview_fn
        self._get_runtime_info = (
            get_runtime_info if get_runtime_info_fn is None else get_runtime_info_fn
        )
        self._server: asyncio.Server | None = None
        self._handlers: set[asyncio.Task[None]] = set()
        self._writers: set[asyncio.StreamWriter] = set()
        self._closing = False
        self._port: int | None = None
        self._capability: str | None = None

    @property
    def address(self) -> tuple[str, int]:
        """Return the exact numeric IPv4 listener address while running."""
        if self._port is None:
            raise StudioHostLifecycleError
        return (_LOOPBACK_HOST, self._port)

    @property
    def origin(self) -> str:
        """Return the capability-free same origin while running."""
        host, port = self.address
        return f"http://{host}:{port}"

    @property
    def launch_url(self) -> str:
        """Return the in-memory bootstrap fragment while running."""
        capability = self._capability
        if capability is None:
            raise StudioHostLifecycleError
        return f"{self.origin}/live#capability={capability}"

    async def start(self) -> None:
        """Bind one OS-assigned IPv4 loopback port within the lifecycle bound."""
        if self._server is not None:
            raise StudioHostLifecycleError
        try:
            async with asyncio.timeout(LIFECYCLE_TIMEOUT_SECONDS):
                await self._start()
        except (TimeoutError, OSError, StudioHostError):
            await self._reset_after_failed_start()
            raise StudioHostLifecycleError from None

    async def close(self) -> None:
        """Release only Host-owned connections and listener state."""
        try:
            async with asyncio.timeout(LIFECYCLE_TIMEOUT_SECONDS):
                await self._close()
        except TimeoutError:
            self._cancel_handlers()
            self._abort_connections()
            self._clear_runtime_state()
            raise StudioHostLifecycleError from None

    async def __aenter__(self) -> StudioHost:
        await self.start()
        return self

    async def __aexit__(
        self,
        _exception_type: type[BaseException] | None,
        _exception: BaseException | None,
        _traceback: object,
    ) -> None:
        await self.close()

    async def _start(self) -> None:
        self._closing = False
        self._capability = secrets.token_urlsafe(32)
        server = await asyncio.start_server(
            self._handle_connection,
            host=_LOOPBACK_HOST,
            port=0,
            family=socket.AF_INET,
            limit=MAX_REQUEST_HEAD_BYTES + 1,
        )
        sockets = tuple(server.sockets or ())
        if len(sockets) != 1 or sockets[0].family != socket.AF_INET:
            server.close()
            await server.wait_closed()
            raise StudioHostLifecycleError
        address = sockets[0].getsockname()
        if address[0] != _LOOPBACK_HOST or not isinstance(address[1], int):
            server.close()
            await server.wait_closed()
            raise StudioHostLifecycleError
        self._server = server
        self._port = address[1]

    async def _reset_after_failed_start(self) -> None:
        server = self._server
        if server is not None:
            server.close()
            await server.wait_closed()
        self._clear_runtime_state()

    async def _close(self) -> None:
        self._closing = True
        server = self._server
        if server is not None:
            # Let callbacks for connections already accepted by the kernel run
            # while the closing guard makes them close immediately.
            await asyncio.sleep(0)
            server.close()
            await asyncio.sleep(0)
            self._cancel_handlers()
            self._close_connections()
        self._cancel_handlers()
        writers = tuple(self._writers)
        self._close_connections()
        current = asyncio.current_task()
        handlers = tuple(task for task in self._handlers if task is not current)
        if handlers:
            await asyncio.gather(*handlers, return_exceptions=True)
        if writers:
            await asyncio.gather(
                *(writer.wait_closed() for writer in writers),
                return_exceptions=True,
            )
        if server is not None:
            await server.wait_closed()
        self._clear_runtime_state()

    def _cancel_handlers(self) -> None:
        current = asyncio.current_task()
        for task in tuple(self._handlers):
            if task is not current:
                task.cancel()

    def _abort_connections(self) -> None:
        for writer in tuple(self._writers):
            writer.transport.abort()

    def _close_connections(self) -> None:
        for writer in tuple(self._writers):
            writer.close()

    def _clear_runtime_state(self) -> None:
        self._server = None
        self._port = None
        self._capability = None
        self._handlers.clear()
        self._writers.clear()

    async def _handle_connection(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        if self._closing:
            writer.close()
            return
        current = asyncio.current_task()
        if current is not None:
            self._handlers.add(current)
        self._writers.add(writer)
        request: _Request | None = None
        try:
            try:
                async with asyncio.timeout(REQUEST_READ_TIMEOUT_SECONDS):
                    request = await _read_request(reader)
            except _RequestTooLarge:
                response = _error_response("request_too_large")
            except (TimeoutError, _RequestInvalid):
                response = _error_response("invalid_request")
            else:
                try:
                    async with asyncio.timeout(APPLICATION_TIMEOUT_SECONDS):
                        response = await self._response_for(request)
                except TimeoutError:
                    response = _error_response("application_error")
                except Exception:
                    response = _error_response("application_error")
            await _write_response(
                writer,
                response,
                suppress_body=request is not None and request.method == "HEAD",
            )
        except (ConnectionError, OSError):
            pass
        finally:
            writer.close()
            if current is not None:
                self._handlers.discard(current)
            self._writers.discard(writer)

    async def _response_for(self, request: _Request) -> _Response:
        host_failure = self._validate_host(request.headers)
        if host_failure is not None:
            return host_failure
        origin_failure = self._validate_origin(request.headers)
        if origin_failure is not None:
            return origin_failure
        if request.method not in {"GET", "HEAD"}:
            return _error_response(
                "method_not_allowed",
                extra_headers=(("Allow", "GET, HEAD"),),
            )
        if "?" in request.target or "#" in request.target:
            return _error_response("invalid_request")
        if not request.target.isascii() or "%" in request.target or "\\" in request.target:
            return _error_response("not_found")

        static_asset = _STATIC_ROUTES.get(request.target)
        if static_asset is not None:
            try:
                body = _read_static_asset(self._asset_root, static_asset[0])
            except _StaticNotFound:
                return _error_response("not_found")
            except _ResponseTooLarge:
                return _error_response("application_error")
            return _Response(200, static_asset[1], body)

        api_route = request.target in {
            "/api/v1/meta",
            "/api/v1/runtime/info",
            "/api/v1/sessions",
        }
        prefix = "/api/v1/sessions/"
        suffix = "/preview"
        preview_session: str | None = None
        if request.target.startswith(prefix) and request.target.endswith(suffix):
            candidate = request.target[len(prefix) : -len(suffix)]
            if candidate and "/" not in candidate:
                api_route = True
                preview_session = candidate
        if not api_route:
            return _error_response("not_found")
        if not self._valid_capability(request.headers):
            return _error_response("request_rejected")
        if request.target == "/api/v1/meta":
            return _json_response(
                {
                    "app_version": __version__,
                    "host_version": HOST_VERSION,
                    "ready": True,
                    "schema_version": STUDIO_SCHEMA_VERSION,
                }
            )
        if request.target == "/api/v1/runtime/info":
            return await self._runtime_info_response()
        if request.target == "/api/v1/sessions":
            return await self._sessions_response()
        if preview_session is None:
            return _error_response("not_found")
        if _SESSION_PATTERN.fullmatch(preview_session) is None:
            return _error_response("invalid_request")
        return await self._preview_response(preview_session)

    def _validate_host(self, headers: Mapping[str, tuple[str, ...]]) -> _Response | None:
        if "forwarded" in headers or any(name.startswith("x-forwarded-") for name in headers):
            return _error_response("host_rejected")
        values = headers.get("host", ())
        if len(values) != 1 or values[0] != f"{_LOOPBACK_HOST}:{self.address[1]}":
            return _error_response("host_rejected")
        return None

    def _validate_origin(
        self,
        headers: Mapping[str, tuple[str, ...]],
    ) -> _Response | None:
        values = headers.get("origin", ())
        if len(values) > 1 or (values and values[0] != self.origin):
            return _error_response("request_rejected")
        return None

    def _valid_capability(self, headers: Mapping[str, tuple[str, ...]]) -> bool:
        expected = self._capability
        values = headers.get(_CAPABILITY_HEADER_KEY, ())
        if expected is None or len(values) != 1 or _TOKEN_PATTERN.fullmatch(values[0]) is None:
            return False
        return secrets.compare_digest(values[0], expected)

    async def _sessions_response(self) -> _Response:
        try:
            sessions = await self._list_sessions()
            if (
                type(sessions) is not tuple
                or any(type(session) is not str for session in sessions)
                or len(sessions) > 64
                or any(_SESSION_PATTERN.fullmatch(session) is None for session in sessions)
                or tuple(sorted(sessions)) != sessions
                or len(set(sessions)) != len(sessions)
            ):
                raise ValueError
            return _json_response(
                {"schema_version": STUDIO_SCHEMA_VERSION, "sessions": list(sessions)}
            )
        except StudioApplicationError as error:
            return _application_error_response(error)
        except Exception:
            return _error_response("sessions_unavailable")

    async def _preview_response(self, session: str) -> _Response:
        try:
            snapshot = await self._get_preview(session)
            if not isinstance(cast(object, snapshot), SimulationPreviewSnapshot):
                raise ValueError
            encoded = render_simulation_preview_json(snapshot).encode("utf-8")
            if len(encoded) > MAX_API_RESPONSE_BYTES:
                raise _ResponseTooLarge
            return _Response(200, "application/json; charset=utf-8", encoded)
        except StudioApplicationError as error:
            return _application_error_response(error)
        except Exception:
            return _error_response("application_error")

    async def _runtime_info_response(self) -> _Response:
        try:
            info = await self._get_runtime_info()
            if (
                not isinstance(cast(object, info), StudioRuntimeInfo)
                or info.schema_version != STUDIO_SCHEMA_VERSION
                or type(info.package_version) is not str
                or not info.package_version.strip()
                or type(info.supported_config_schemas) is not tuple
                or any(
                    type(version) is not str or not version.strip()
                    for version in info.supported_config_schemas
                )
                or type(info.registered_models) is not tuple
                or len(info.registered_models) > 64
            ):
                raise ValueError
            serialized_models: list[dict[str, object]] = []
            seen_models: set[str] = set()
            for item in info.registered_models:
                if (
                    not isinstance(cast(object, item), RuntimeModelSummary)
                    or type(item.model) is not str
                    or not item.model.strip()
                    or item.model in seen_models
                    or type(item.category) is not str
                    or not item.category.strip()
                    or type(item.capabilities) is not tuple
                    or any(
                        type(cap) is not str or not cap.strip()
                        for cap in item.capabilities
                    )
                ):
                    raise ValueError
                seen_models.add(item.model)
                serialized_models.append(
                    {
                        "capabilities": list(item.capabilities),
                        "category": item.category,
                        "model": item.model,
                    }
                )
            return _json_response(
                {
                    "package_version": info.package_version,
                    "registered_models": serialized_models,
                    "schema_version": STUDIO_SCHEMA_VERSION,
                    "supported_config_schemas": list(info.supported_config_schemas),
                }
            )
        except StudioApplicationError as error:
            return _application_error_response(error)
        except Exception:
            return _error_response("application_error")


async def _read_request(reader: asyncio.StreamReader) -> _Request:
    total = 0
    request_line = await _read_line(reader, MAX_REQUEST_LINE_BYTES)
    total += len(request_line)
    try:
        decoded_request = request_line[:-2].decode("ascii")
    except UnicodeDecodeError as error:
        raise _RequestInvalid from error
    parts = decoded_request.split(" ")
    if len(parts) != 3 or not all(parts) or parts[2] != "HTTP/1.1":
        raise _RequestInvalid
    method, target, _version = parts
    if not method.isascii() or not method.isupper() or not method.isalpha():
        raise _RequestInvalid

    headers: dict[str, list[str]] = {}
    field_count = 0
    while True:
        line = await _read_line(reader, MAX_HEADER_LINE_BYTES)
        total += len(line)
        if total > MAX_REQUEST_HEAD_BYTES:
            raise _RequestTooLarge
        if line == b"\r\n":
            break
        field_count += 1
        if field_count > MAX_HEADER_FIELDS:
            raise _RequestTooLarge
        try:
            decoded = line[:-2].decode("iso-8859-1")
        except UnicodeDecodeError as error:
            raise _RequestInvalid from error
        if ":" not in decoded:
            raise _RequestInvalid
        name, value = decoded.split(":", 1)
        if _HEADER_NAME_PATTERN.fullmatch(name) is None:
            raise _RequestInvalid
        value = value.strip(" \t")
        if any(
            (ord(character) < 32 and character != "\t") or ord(character) == 127
            for character in value
        ):
            raise _RequestInvalid
        headers.setdefault(name.lower(), []).append(value)

    if "transfer-encoding" in headers:
        raise _RequestInvalid
    content_lengths = headers.get("content-length", [])
    if len(content_lengths) > 1 or (content_lengths and content_lengths[0] != "0"):
        raise _RequestInvalid
    if "expect" in headers or "upgrade" in headers:
        raise _RequestInvalid
    return _Request(method, target, {name: tuple(values) for name, values in headers.items()})


async def _read_line(reader: asyncio.StreamReader, limit: int) -> bytes:
    try:
        line = await reader.readuntil(b"\r\n")
    except (asyncio.IncompleteReadError, asyncio.LimitOverrunError) as error:
        if isinstance(error, asyncio.LimitOverrunError):
            raise _RequestTooLarge from error
        raise _RequestInvalid from error
    if len(line) > limit:
        raise _RequestTooLarge
    return line


async def _write_response(
    writer: asyncio.StreamWriter,
    response: _Response,
    *,
    suppress_body: bool,
) -> None:
    reason = _STATUS_REASONS[response.status]
    lines = [
        f"HTTP/1.1 {response.status} {reason}",
        f"Content-Type: {response.content_type}",
        f"Content-Length: {len(response.body)}",
        "Connection: close",
    ]
    lines.extend(f"{name}: {value}" for name, value in _SECURITY_HEADERS)
    lines.extend(f"{name}: {value}" for name, value in response.extra_headers)
    head = ("\r\n".join(lines) + "\r\n\r\n").encode("ascii")
    writer.write(head if suppress_body else head + response.body)
    await writer.drain()


def _json_response(document: Mapping[str, object]) -> _Response:
    encoded = json.dumps(
        document,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    if len(encoded) > MAX_API_RESPONSE_BYTES:
        return _error_response("application_error")
    return _Response(200, "application/json; charset=utf-8", encoded)


def _error_response(
    code: str,
    *,
    extra_headers: tuple[tuple[str, str], ...] = (),
) -> _Response:
    status, message = _ERRORS[code]
    body = json.dumps(
        {
            "error": {"code": code, "message": message},
            "schema_version": STUDIO_SCHEMA_VERSION,
        },
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("ascii")
    return _Response(status, "application/json; charset=utf-8", body, extra_headers)


def _application_error_response(error: StudioApplicationError) -> _Response:
    return _error_response(_APPLICATION_ERROR_CODES[error.code])


def _validate_asset_root(root: Path) -> Path:
    if not root.is_absolute():
        raise StudioHostConfigurationError
    try:
        result = os.lstat(root)
    except OSError:
        raise StudioHostConfigurationError from None
    if (
        not stat.S_ISDIR(result.st_mode)
        or stat.S_ISLNK(result.st_mode)
        or result.st_uid != os.geteuid()
        or stat.S_IMODE(result.st_mode) & 0o022
    ):
        raise StudioHostConfigurationError
    return root


def _read_static_asset(root: Path, name: str) -> bytes:
    root_before = _safe_static_status(root, expected_directory=True)
    path = root / name
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError:
        raise _StaticNotFound from None
    try:
        before = os.fstat(descriptor)
        if not _safe_static_file(before):
            raise _StaticNotFound
        if before.st_size > MAX_STATIC_RESPONSE_BYTES:
            raise _ResponseTooLarge
        body = os.read(descriptor, MAX_STATIC_RESPONSE_BYTES + 1)
        after = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    root_after = _safe_static_status(root, expected_directory=True)
    if (
        len(body) > MAX_STATIC_RESPONSE_BYTES
        or _status_signature(before) != _status_signature(after)
        or _status_signature(root_before) != _status_signature(root_after)
        or len(body) != before.st_size
    ):
        raise _ResponseTooLarge
    return body


def _safe_static_status(path: Path, *, expected_directory: bool) -> os.stat_result:
    try:
        result = os.lstat(path)
    except OSError:
        raise _StaticNotFound from None
    kind_matches = stat.S_ISDIR(result.st_mode) if expected_directory else stat.S_ISREG(
        result.st_mode
    )
    if (
        not kind_matches
        or stat.S_ISLNK(result.st_mode)
        or result.st_uid != os.geteuid()
        or stat.S_IMODE(result.st_mode) & 0o022
    ):
        raise _StaticNotFound
    return result


def _safe_static_file(result: os.stat_result) -> bool:
    return (
        stat.S_ISREG(result.st_mode)
        and result.st_uid == os.geteuid()
        and not stat.S_IMODE(result.st_mode) & 0o022
    )


def _status_signature(
    result: os.stat_result,
) -> tuple[int, int, int, int, int, int, int]:
    return (
        result.st_dev,
        result.st_ino,
        result.st_mode,
        result.st_uid,
        result.st_size,
        result.st_mtime_ns,
        result.st_ctime_ns,
    )
