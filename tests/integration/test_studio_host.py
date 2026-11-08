import asyncio
import hashlib
import stat
import tempfile
from collections.abc import Iterator
from pathlib import Path
from urllib.parse import urlsplit

import pytest

from hiyelx.config import ResourceDefinition, RuntimeConfig
from hiyelx.models import ModelRegistry
from hiyelx.resources import ResourceIdentity
from hiyelx.runtime.control import (
    LocalControlServer,
    StopCoordinator,
    configuration_fingerprint,
    request_status,
    reserve_session,
)
from hiyelx.runtime.operations import RuntimeOperations
from hiyelx.runtime.state import RuntimeManagerState
from hiyelx.simulation import (
    SimulationPreviewSnapshot,
    register_simulated_motor,
    render_simulation_preview_json,
)
from hiyelx.studio.application import get_preview, list_sessions
from hiyelx.studio.host import CAPABILITY_HEADER, StudioHost


@pytest.mark.asyncio
async def test_http_preview_is_read_only_and_host_shutdown_preserves_runtime(
    tmp_path: Path,
    short_state_directory: Path,
) -> None:
    state_root = short_state_directory
    asset_root = _asset_root(tmp_path)
    config = RuntimeConfig(
        schema_version="1",
        resources=[
            ResourceDefinition(
                identity=ResourceIdentity("sim_motor"),
                model="motor.simulated",
                settings={},
            )
        ],
    )
    registry = ModelRegistry()
    register_simulated_motor(registry)
    operations = RuntimeOperations(config, registry)
    await operations.start()
    owned = reserve_session("studio-live", state_directory=state_root)
    control_server = LocalControlServer(owned.layout, operations, StopCoordinator())

    async def observable_sessions() -> tuple[str, ...]:
        return await list_sessions(state_directory=state_root)

    async def preview(session: str) -> SimulationPreviewSnapshot:
        return await get_preview(session, state_directory=state_root)

    host = StudioHost(
        asset_root,
        list_sessions_fn=observable_sessions,
        get_preview_fn=preview,
    )
    try:
        await control_server.start()
        owned.publish(configuration_fingerprint(config))
        runtime_before = operations.snapshot()
        preview_before = operations.simulation_preview_snapshot()
        artifacts_before = _artifact_snapshot(state_root)

        await host.start()
        token = urlsplit(host.launch_url).fragment.removeprefix("capability=")
        sessions_response = await _request(host, "/api/v1/sessions", token)
        preview_response = await _request(
            host,
            "/api/v1/sessions/studio-live/preview",
            token,
        )

        assert sessions_response == b'{"schema_version":"1","sessions":["studio-live"]}'
        assert preview_response == render_simulation_preview_json(preview_before).encode()
        assert operations.snapshot() == runtime_before
        assert operations.simulation_preview_snapshot() == preview_before
        assert _artifact_snapshot(state_root) == artifacts_before

        await host.close()
        status = await request_status("studio-live", state_directory=state_root)
        assert status.manager_state is RuntimeManagerState.RUNNING
        assert operations.snapshot() == runtime_before
        assert operations.simulation_preview_snapshot() == preview_before
        assert _artifact_snapshot(state_root) == artifacts_before
    finally:
        await host.close()
        await control_server.close()
        await control_server.wait_handlers()
        await operations.safe_stop()
        await operations.shutdown()
        assert owned.cleanup(final=True)


async def _request(host: StudioHost, path: str, capability: str) -> bytes:
    reader, writer = await asyncio.open_connection(*host.address)
    request = (
        f"GET {path} HTTP/1.1\r\n"
        f"Host: {host.address[0]}:{host.address[1]}\r\n"
        f"{CAPABILITY_HEADER}: {capability}\r\n"
        "Connection: close\r\n\r\n"
    ).encode("ascii")
    writer.write(request)
    await writer.drain()
    response = await reader.read()
    writer.close()
    await writer.wait_closed()
    head, separator, body = response.partition(b"\r\n\r\n")
    assert separator == b"\r\n\r\n"
    assert head.startswith(b"HTTP/1.1 200 OK\r\n")
    return body


def _asset_root(tmp_path: Path) -> Path:
    root = tmp_path / "assets"
    root.mkdir(mode=0o700)
    for name in ("index.html", "studio.css", "fixtures.js", "app.js", "host-client.js"):
        path = root / name
        path.write_bytes(name.encode("ascii"))
        path.chmod(0o600)
    return root


def _artifact_snapshot(root: Path) -> dict[str, tuple[int, int, int, int, str | None]]:
    snapshot: dict[str, tuple[int, int, int, int, str | None]] = {}
    for path in (root, *sorted(root.rglob("*"))):
        result = path.lstat()
        digest = None
        if stat.S_ISREG(result.st_mode):
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
        snapshot[str(path.relative_to(root))] = (
            result.st_ino,
            result.st_mode,
            result.st_size,
            result.st_mtime_ns,
            digest,
        )
    return snapshot


@pytest.fixture
def short_state_directory() -> Iterator[Path]:
    with tempfile.TemporaryDirectory(prefix="hiyelx-studio-", dir="/private/tmp") as path:
        yield Path(path)
