import asyncio
import base64
import hashlib
import json
import socket
import time
from contextlib import suppress
from pathlib import Path
from urllib.parse import urlsplit

import pytest

from hiyelx.resources import HealthStatus, LifecycleState, ResourceIdentity
from hiyelx.runtime.state import RuntimeManagerState
from hiyelx.simulation import (
    SimulationMotorPreviewState,
    SimulationPreviewResourceSnapshot,
    SimulationPreviewSnapshot,
    render_simulation_preview_json,
)
from hiyelx.studio import host as host_module
from hiyelx.studio.application import StudioApplicationError, StudioErrorCode
from hiyelx.studio.host import (
    CAPABILITY_HEADER,
    MAX_API_RESPONSE_BYTES,
    MAX_HEADER_FIELDS,
    MAX_HEADER_LINE_BYTES,
    MAX_REQUEST_LINE_BYTES,
    MAX_STATIC_RESPONSE_BYTES,
    StudioHost,
    StudioHostConfigurationError,
    StudioHostLifecycleError,
)

_P1_HASHES = {
    "index.html": "b53a73f667a22caeb5c98f7ac57f51d444311f95f65bf53005723ba09c608660",
    "studio.css": "16e5d0d4545a123c1ccd2a08449f3c8863304735a75f011f130f20f92d20ea01",
    "fixtures.js": "19a6f1382780e6e39e961c8498c8cc9fb2030f382003dda931d2a33da806f864",
    "app.js": "9b15474eee9dea77371caffedbb3cedf1c2542a5fd9870be105e0518f599d9ca",
}
_SECURITY_HEADERS = {
    "cache-control": "no-store, max-age=0",
    "content-security-policy": (
        "default-src 'self'; base-uri 'none'; connect-src 'self'; "
        "form-action 'none'; frame-ancestors 'none'; img-src 'self'; "
        "object-src 'none'; script-src 'self'; style-src 'self'"
    ),
    "cross-origin-opener-policy": "same-origin",
    "cross-origin-resource-policy": "same-origin",
    "permissions-policy": (
        "camera=(), geolocation=(), microphone=(), serial=(), usb=()"
    ),
    "referrer-policy": "no-referrer",
    "x-content-type-options": "nosniff",
    "x-frame-options": "DENY",
}


@pytest.mark.asyncio
async def test_authorized_get_and_head_routes_are_exact_and_canonical(
    asset_root: Path,
) -> None:
    host = _host(asset_root)
    await host.start()
    try:
        token = _capability(host)
        for route, name, content_type in (
            ("/", "index.html", "text/html; charset=utf-8"),
            ("/studio.css", "studio.css", "text/css; charset=utf-8"),
            ("/fixtures.js", "fixtures.js", "text/javascript; charset=utf-8"),
            ("/app.js", "app.js", "text/javascript; charset=utf-8"),
            ("/host-client.js", "host-client.js", "text/javascript; charset=utf-8"),
        ):
            response = await _exchange(host, _request(host, route))
            assert response.status == 200
            assert response.body == (asset_root / name).read_bytes()
            assert response.headers["content-type"] == content_type

            head = await _exchange(host, _request(host, route, method="HEAD"))
            assert head.status == 200
            assert head.body == b""
            assert int(head.headers["content-length"]) == len(response.body)

        meta = await _api(host, "/api/v1/meta", token)
        assert json.loads(meta.body) == {
            "app_version": "0.2.0a1",
            "host_version": "1",
            "ready": True,
            "schema_version": "1",
        }
        sessions = await _api(host, "/api/v1/sessions", token)
        assert sessions.body == b'{"schema_version":"1","sessions":["alpha"]}'
        preview = await _api(host, "/api/v1/sessions/alpha/preview", token)
        assert preview.body == render_simulation_preview_json(_snapshot()).encode()

        preview_head = await _api(
            host,
            "/api/v1/sessions/alpha/preview",
            token,
            method="HEAD",
        )
        assert preview_head.status == 200
        assert preview_head.body == b""
        assert int(preview_head.headers["content-length"]) == len(preview.body)
    finally:
        await host.close()


@pytest.mark.asyncio
async def test_capability_is_256_bit_fragment_only_and_required_for_api(
    asset_root: Path,
) -> None:
    host = _host(asset_root)
    await host.start()
    try:
        split = urlsplit(host.launch_url)
        assert split.query == ""
        assert split.fragment.startswith("capability=")
        token = _capability(host)
        padded = token + "=" * (-len(token) % 4)
        assert len(base64.urlsafe_b64decode(padded)) == 32

        static = await _exchange(host, _request(host, "/"))
        assert static.status == 200
        ignored = await _exchange(
            host,
            _request(host, "/", headers=((CAPABILITY_HEADER, "invalid"),)),
        )
        assert ignored.status == 200
        for value in (None, "x" * 43, token + "x"):
            headers = () if value is None else ((CAPABILITY_HEADER, value),)
            response = await _exchange(
                host,
                _request(host, "/api/v1/meta", headers=headers),
            )
            assert response.status == 403
            assert _error_code(response) == "request_rejected"
            assert token.encode() not in response.raw

        duplicated = await _exchange(
            host,
            _request(
                host,
                "/api/v1/meta",
                headers=(
                    (CAPABILITY_HEADER, token),
                    (CAPABILITY_HEADER, token),
                ),
            ),
        )
        assert duplicated.status == 403

        valid = await _api(host, "/api/v1/meta", token)
        assert valid.status == 200
        assert token.encode() not in valid.raw
    finally:
        await host.close()


@pytest.mark.asyncio
async def test_capability_comparison_uses_constant_time_primitive(
    asset_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    comparisons = 0
    original = host_module.secrets.compare_digest

    def compare(first: str, second: str) -> bool:
        nonlocal comparisons
        comparisons += 1
        return original(first, second)

    monkeypatch.setattr(host_module.secrets, "compare_digest", compare)
    host = _host(asset_root)
    await host.start()
    try:
        invalid = await _api(host, "/api/v1/meta", "x" * 43)
        valid = await _api(host, "/api/v1/meta", _capability(host))
        assert invalid.status == 403
        assert valid.status == 200
        assert comparisons == 2
    finally:
        await host.close()


@pytest.mark.asyncio
async def test_invalid_session_is_rejected_before_application_access(
    asset_root: Path,
) -> None:
    calls = 0

    async def preview(_session: str) -> SimulationPreviewSnapshot:
        nonlocal calls
        calls += 1
        return _snapshot()

    host = StudioHost(asset_root, get_preview_fn=preview)
    await host.start()
    try:
        response = await _api(
            host,
            "/api/v1/sessions/INVALID/preview",
            _capability(host),
        )
        assert response.status == 400
        assert _error_code(response) == "invalid_request"
        assert calls == 0
    finally:
        await host.close()


@pytest.mark.parametrize(
    ("headers", "status", "code"),
    (
        ((), 421, "host_rejected"),
        ((("Host", "localhost:1"),), 421, "host_rejected"),
        ((("Host", "127.0.0.1.evil:1"),), 421, "host_rejected"),
        ((("Host", "127.0.0.1:1"),), 421, "host_rejected"),
        ((("X-Forwarded-Host", "127.0.0.1"),), 421, "host_rejected"),
        ((("Origin", "null"),), 403, "request_rejected"),
        ((("Origin", "https://example.invalid"),), 403, "request_rejected"),
    ),
)
@pytest.mark.asyncio
async def test_host_origin_and_dns_rebinding_defenses(
    headers: tuple[tuple[str, str], ...],
    status: int,
    code: str,
    asset_root: Path,
) -> None:
    host = _host(asset_root)
    await host.start()
    try:
        supplied = headers
        if not any(name.lower() == "host" for name, _value in headers):
            supplied = (("Host", f"127.0.0.1:{host.address[1]}"),) + supplied
        if headers == ():
            supplied = ()
        response = await _exchange(host, _raw("GET", "/", supplied))
        assert response.status == status
        assert _error_code(response) == code

        exact_origin = await _exchange(
            host,
            _request(host, "/", headers=(("Origin", host.origin),)),
        )
        assert exact_origin.status == 200
    finally:
        await host.close()


@pytest.mark.asyncio
async def test_duplicate_host_and_origin_headers_fail_closed(asset_root: Path) -> None:
    host = _host(asset_root)
    await host.start()
    try:
        authority = f"127.0.0.1:{host.address[1]}"
        duplicated_host = await _exchange(
            host,
            _raw("GET", "/", (("Host", authority), ("Host", authority))),
        )
        duplicated_origin = await _exchange(
            host,
            _raw(
                "GET",
                "/",
                (
                    ("Host", authority),
                    ("Origin", host.origin),
                    ("Origin", host.origin),
                ),
            ),
        )
        assert duplicated_host.status == 421
        assert duplicated_origin.status == 403
    finally:
        await host.close()


@pytest.mark.asyncio
async def test_listener_is_ipv4_numeric_loopback_only(asset_root: Path) -> None:
    host = _host(asset_root)
    await host.start()
    port = host.address[1]
    try:
        assert host.address == ("127.0.0.1", port)
        reader, writer = await asyncio.open_connection(
            "127.0.0.1",
            port,
            family=socket.AF_INET,
        )
        writer.close()
        await writer.wait_closed()
        del reader
        with pytest.raises(OSError):
            await asyncio.open_connection("::1", port, family=socket.AF_INET6)
    finally:
        await host.close()


@pytest.mark.parametrize(
    ("case", "status", "code"),
    (
        ("post", 405, "method_not_allowed"),
        ("options", 405, "method_not_allowed"),
        ("missing", 404, "not_found"),
        ("traversal", 404, "not_found"),
        ("query", 400, "invalid_request"),
        ("body", 400, "invalid_request"),
        ("transfer", 400, "invalid_request"),
        ("http10", 400, "invalid_request"),
    ),
)
@pytest.mark.asyncio
async def test_methods_routes_queries_bodies_and_malformed_requests_are_rejected(
    case: str,
    status: int,
    code: str,
    asset_root: Path,
) -> None:
    host = _host(asset_root)
    await host.start()
    try:
        requests = {
            "post": _request(host, "/", method="POST"),
            "options": _request(host, "/", method="OPTIONS"),
            "missing": _request(host, "/missing"),
            "traversal": _request(host, "/../index.html"),
            "query": _request(host, "/?query=1"),
            "body": _request(host, "/", headers=(("Content-Length", "1"),)),
            "transfer": _request(
                host,
                "/",
                headers=(("Transfer-Encoding", "chunked"),),
            ),
            "http10": _raw(
                "GET",
                "/",
                (("Host", f"127.0.0.1:{host.address[1]}"),),
                version="HTTP/1.0",
            ),
        }
        request = requests[case]
        response = await _exchange(host, request)
        assert response.status == status
        assert _error_code(response) == code
        if status == 405:
            assert response.headers["allow"] == "GET, HEAD"
    finally:
        await host.close()


@pytest.mark.parametrize("oversize", ("request-line", "header-line", "count", "total"))
@pytest.mark.asyncio
async def test_request_head_limits_return_sanitized_413(
    oversize: str,
    asset_root: Path,
) -> None:
    host = _host(asset_root)
    await host.start()
    try:
        authority = f"127.0.0.1:{host.address[1]}"
        if oversize == "request-line":
            target = "/" + "x" * MAX_REQUEST_LINE_BYTES
            request = _raw("GET", target, (("Host", authority),))
        elif oversize == "header-line":
            request = _raw(
                "GET",
                "/",
                (("Host", authority), ("X-Large", "x" * MAX_HEADER_LINE_BYTES)),
            )
        elif oversize == "count":
            request = _raw(
                "GET",
                "/",
                (("Host", authority),)
                + tuple((f"X-{index}", "x") for index in range(MAX_HEADER_FIELDS)),
            )
        else:
            request = _raw(
                "GET",
                "/",
                (("Host", authority),)
                + tuple((f"X-{index}", "x" * 260) for index in range(63)),
            )
        response = await _exchange(host, request)
        assert response.status == 413
        assert _error_code(response) == "request_too_large"
    finally:
        await host.close()


@pytest.mark.asyncio
async def test_request_read_deadline_is_sanitized(
    asset_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(host_module, "REQUEST_READ_TIMEOUT_SECONDS", 0.01)
    host = _host(asset_root)
    await host.start()
    try:
        reader, writer = await asyncio.open_connection(*host.address)
        writer.write(b"GET / HTTP/1.1\r\n")
        await writer.drain()
        raw = await reader.read()
        response = _parse(raw)
        assert response.status == 400
        assert _error_code(response) == "invalid_request"
        writer.close()
        await writer.wait_closed()
    finally:
        await host.close()


@pytest.mark.asyncio
async def test_static_and_api_response_limits_fail_closed(
    asset_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    host = _host(asset_root)
    await host.start()
    try:
        (asset_root / "app.js").write_bytes(b"x" * (MAX_STATIC_RESPONSE_BYTES + 1))
        static = await _exchange(host, _request(host, "/app.js"))
        assert static.status == 500
        assert _error_code(static) == "application_error"

        def oversized_preview(_snapshot: SimulationPreviewSnapshot) -> str:
            return "x" * (MAX_API_RESPONSE_BYTES + 1)

        monkeypatch.setattr(
            host_module,
            "render_simulation_preview_json",
            oversized_preview,
        )
        preview = await _api(
            host,
            "/api/v1/sessions/alpha/preview",
            _capability(host),
        )
        assert preview.status == 500
        assert _error_code(preview) == "application_error"
    finally:
        await host.close()


@pytest.mark.asyncio
async def test_static_symlinks_and_traversal_are_never_served(
    asset_root: Path,
    tmp_path: Path,
) -> None:
    secret = tmp_path / "private.txt"
    secret.write_text("private-path=/tmp/secret pid=7")
    (asset_root / "app.js").unlink()
    (asset_root / "app.js").symlink_to(secret)
    host = _host(asset_root)
    await host.start()
    try:
        response = await _exchange(host, _request(host, "/app.js"))
        assert response.status == 404
        assert b"private" not in response.raw
        traversal = await _exchange(host, _request(host, "/../private.txt"))
        assert traversal.status == 404
        assert secret.read_text() not in traversal.raw.decode()
    finally:
        await host.close()

    linked_root = tmp_path / "linked-assets"
    linked_root.symlink_to(asset_root, target_is_directory=True)
    with pytest.raises(StudioHostConfigurationError):
        StudioHost(linked_root)


def test_unsafe_static_root_mode_is_rejected(asset_root: Path) -> None:
    asset_root.chmod(0o770)
    with pytest.raises(StudioHostConfigurationError):
        StudioHost(asset_root)


@pytest.mark.asyncio
async def test_every_response_has_security_headers_and_no_fingerprint_or_cors(
    asset_root: Path,
) -> None:
    host = _host(asset_root)
    await host.start()
    try:
        for response in (
            await _exchange(host, _request(host, "/")),
            await _api(host, "/api/v1/meta", _capability(host)),
            await _exchange(host, _request(host, "/missing")),
        ):
            for name, expected in _SECURITY_HEADERS.items():
                assert response.headers[name] == expected
            assert "server" not in response.headers
            assert not any(name.startswith("access-control-") for name in response.headers)
        missing = await _exchange(host, _request(host, "/missing"))
        assert missing.body == (
            b'{"error":{"code":"not_found","message":"Studio resource was not '
            b'found."},"schema_version":"1"}'
        )
    finally:
        await host.close()


@pytest.mark.asyncio
async def test_application_failures_are_fixed_and_hide_private_metadata(
    asset_root: Path,
) -> None:
    async def failed_sessions() -> tuple[str, ...]:
        raise OSError("/tmp/private manifest.json pid=42 secret=value")

    async def failed_preview(_session: str) -> SimulationPreviewSnapshot:
        raise StudioApplicationError(StudioErrorCode.PREVIEW_UNAVAILABLE)

    host = StudioHost(
        asset_root,
        list_sessions_fn=failed_sessions,
        get_preview_fn=failed_preview,
    )
    await host.start()
    try:
        token = _capability(host)
        sessions = await _api(host, "/api/v1/sessions", token)
        assert sessions.status == 503
        assert _error_code(sessions) == "sessions_unavailable"
        preview = await _api(host, "/api/v1/sessions/alpha/preview", token)
        assert preview.status == 503
        assert _error_code(preview) == "preview_unavailable"
        combined = sessions.raw + preview.raw
        for private in (b"/tmp/", b"manifest", b"pid", b"secret", b"protocol"):
            assert private not in combined.lower()
    finally:
        await host.close()


@pytest.mark.asyncio
async def test_start_and_shutdown_are_bounded_idempotent_and_host_owned(
    asset_root: Path,
) -> None:
    calls: list[str] = []

    async def sessions() -> tuple[str, ...]:
        calls.append("sessions")
        return ()

    async def preview(_session: str) -> SimulationPreviewSnapshot:
        calls.append("preview")
        return _snapshot()

    before = _asset_snapshot(asset_root)
    host = StudioHost(
        asset_root,
        list_sessions_fn=sessions,
        get_preview_fn=preview,
    )
    started = time.monotonic()
    await host.start()
    port = host.address[1]
    assert time.monotonic() - started < 3
    assert calls == []
    with pytest.raises(StudioHostLifecycleError):
        await host.start()

    reader, writer = await asyncio.open_connection(*host.address)
    writer.write(b"GET / HTTP/1.1\r\n")
    await writer.drain()
    closed = time.monotonic()
    await host.close()
    assert time.monotonic() - closed < 3
    with suppress(ConnectionResetError):
        assert await reader.read() == b""
    writer.close()
    with suppress(ConnectionResetError):
        await writer.wait_closed()
    await host.close()
    assert calls == []
    assert _asset_snapshot(asset_root) == before
    with pytest.raises(StudioHostLifecycleError):
        _ = host.origin
    with pytest.raises(OSError):
        await asyncio.open_connection("127.0.0.1", port)


def test_p1_assets_remain_byte_identical() -> None:
    root = Path(__file__).resolve().parents[3] / "studio"
    assert {
        name: hashlib.sha256((root / name).read_bytes()).hexdigest()
        for name in _P1_HASHES
    } == _P1_HASHES


class _ParsedResponse:
    def __init__(self, raw: bytes) -> None:
        self.raw = raw
        head, separator, body = raw.partition(b"\r\n\r\n")
        assert separator == b"\r\n\r\n"
        lines = head.decode("ascii").split("\r\n")
        self.status = int(lines[0].split(" ")[1])
        self.headers = {
            name.lower(): value.strip()
            for name, value in (line.split(":", 1) for line in lines[1:])
        }
        self.body = body


def _parse(raw: bytes) -> _ParsedResponse:
    return _ParsedResponse(raw)


async def _exchange(host: StudioHost, request: bytes) -> _ParsedResponse:
    reader, writer = await asyncio.open_connection(
        *host.address,
        family=socket.AF_INET,
    )
    writer.write(request)
    await writer.drain()
    raw = await reader.read()
    writer.close()
    await writer.wait_closed()
    return _parse(raw)


def _request(
    host: StudioHost,
    target: str,
    *,
    method: str = "GET",
    headers: tuple[tuple[str, str], ...] = (),
) -> bytes:
    return _raw(
        method,
        target,
        (("Host", f"127.0.0.1:{host.address[1]}"),) + headers,
    )


def _raw(
    method: str,
    target: str,
    headers: tuple[tuple[str, str], ...],
    *,
    version: str = "HTTP/1.1",
) -> bytes:
    lines = [f"{method} {target} {version}"]
    lines.extend(f"{name}: {value}" for name, value in headers)
    return ("\r\n".join(lines) + "\r\n\r\n").encode("ascii")


async def _api(
    host: StudioHost,
    target: str,
    token: str,
    *,
    method: str = "GET",
) -> _ParsedResponse:
    return await _exchange(
        host,
        _request(
            host,
            target,
            method=method,
            headers=(("X-HIYELX-Studio-Capability", token),),
        ),
    )


def _capability(host: StudioHost) -> str:
    fragment = urlsplit(host.launch_url).fragment
    name, token = fragment.split("=", 1)
    assert name == "capability"
    return token


def _error_code(response: _ParsedResponse) -> str:
    return str(json.loads(response.body)["error"]["code"])


def _host(asset_root: Path) -> StudioHost:
    async def sessions() -> tuple[str, ...]:
        return ("alpha",)

    async def preview(session: str) -> SimulationPreviewSnapshot:
        assert session == "alpha"
        return _snapshot()

    return StudioHost(
        asset_root,
        list_sessions_fn=sessions,
        get_preview_fn=preview,
    )


def _snapshot() -> SimulationPreviewSnapshot:
    return SimulationPreviewSnapshot(
        schema_version="1",
        runtime_state=RuntimeManagerState.RUNNING,
        resources=(
            SimulationPreviewResourceSnapshot(
                identity=ResourceIdentity("sim_motor"),
                kind="motor",
                lifecycle_state=LifecycleState.RUNNING,
                health_status=HealthStatus.HEALTHY,
                health_summary=None,
                state=SimulationMotorPreviewState(1.25, 0.5, 2.5, 3),
            ),
        ),
    )


def _asset_snapshot(root: Path) -> dict[str, tuple[int, int, int, bytes]]:
    return {
        path.name: (
            path.stat().st_mode,
            path.stat().st_mtime_ns,
            path.stat().st_ctime_ns,
            path.read_bytes(),
        )
        for path in sorted(root.iterdir())
    }


@pytest.fixture
def asset_root(tmp_path: Path) -> Path:
    root = tmp_path / "assets"
    root.mkdir(mode=0o700)
    assets = {
        "index.html": "<!doctype html><title>Studio</title>",
        "studio.css": "body { color: black; }",
        "fixtures.js": "window.fixtures = [];",
        "app.js": "window.app = {};",
        "host-client.js": "void 0;",
    }
    for name, content in assets.items():
        path = root / name
        path.write_text(content)
        path.chmod(0o644)
    return root
