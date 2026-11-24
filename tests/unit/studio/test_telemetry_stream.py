import asyncio
import json
from pathlib import Path
from typing import TypedDict, cast
from urllib.parse import urlsplit

import pytest

from hiyelx.resources import HealthStatus, LifecycleState, ResourceIdentity
from hiyelx.runtime.state import RuntimeManagerState
from hiyelx.simulation import (
    SimulationMotorPreviewState,
    SimulationPreviewResourceSnapshot,
    SimulationPreviewSnapshot,
)
from hiyelx.studio.application import StudioApplicationError, StudioErrorCode
from hiyelx.studio.host import CAPABILITY_HEADER, StudioHost
from hiyelx.studio.launcher import STUDIO_ASSET_NAMES
from hiyelx.studio.telemetry import (
    BoundedTelemetryRingBuffer,
    classify_fault,
)


def _snapshot(
    *,
    revision: int = 1,
    health_status: HealthStatus = HealthStatus.HEALTHY,
    health_summary: str | None = None,
) -> SimulationPreviewSnapshot:
    return SimulationPreviewSnapshot(
        schema_version="1",
        runtime_state=RuntimeManagerState.RUNNING,
        resources=(
            SimulationPreviewResourceSnapshot(
                identity=ResourceIdentity("sim_motor"),
                kind="motor",
                lifecycle_state=LifecycleState.RUNNING,
                health_status=health_status,
                health_summary=health_summary,
                state=SimulationMotorPreviewState(
                    angular_position_radians=0.25 * revision,
                    angular_velocity_radians_per_second=0.5,
                    simulation_time_seconds=1.0 * revision,
                    revision=revision,
                ),
            ),
        ),
    )


def _stage_assets(tmp_path: Path) -> Path:
    root = tmp_path / "assets"
    root.mkdir(mode=0o700)
    for name in STUDIO_ASSET_NAMES:
        target = root / name
        target.write_bytes(b"ok")
        target.chmod(0o600)
    return root


def test_ring_buffer_drop_oldest_backpressure_and_fault_taxonomy() -> None:
    buf: BoundedTelemetryRingBuffer[int] = BoundedTelemetryRingBuffer(capacity=3)
    assert buf.push(1) is False
    assert buf.push(2) is False
    assert buf.push(3) is False
    assert buf.push(4) is True
    assert buf.push(5) is True
    assert buf.snapshot() == (3, 4, 5)
    assert buf.dropped_count == 2

    deadline = classify_fault("deadline exceeded during motor command")
    assert deadline.fault_code == "OPERATION_DEADLINE_EXCEEDED"
    assert deadline.severity == "error"

    safe_stop = classify_fault("safe-stop failed during shutdown")
    assert safe_stop.fault_code == "SAFE_STOP_FAILED"

    stopped = classify_fault("session_not_running")
    assert stopped.fault_code == "RUNTIME_SESSION_STOPPED"


@pytest.mark.asyncio
async def test_sse_stream_requires_security_guards_and_emits_sequenced_events(
    tmp_path: Path,
) -> None:
    calls = 0

    async def preview(session: str) -> SimulationPreviewSnapshot:
        nonlocal calls
        if session != "alpha":
            raise StudioApplicationError(StudioErrorCode.SESSION_NOT_RUNNING)
        calls += 1
        summary = "deadline exceeded during motor command" if calls == 2 else None
        status = HealthStatus.DEGRADED if calls == 2 else HealthStatus.HEALTHY
        return _snapshot(revision=calls, health_status=status, health_summary=summary)

    host = StudioHost(
        _stage_assets(tmp_path),
        list_sessions_fn=lambda: asyncio.sleep(0, result=("alpha",)),
        get_preview_fn=preview,
        stream_interval_seconds=0.01,
        max_stream_events=2,
    )
    await host.start()
    try:
        token = urlsplit(host.launch_url).fragment.removeprefix("capability=")

        # Reject missing capability (403)
        status_no_cap, _headers, body_no_cap = await _raw_get(
            host, "/api/v1/sessions/alpha/stream"
        )
        assert status_no_cap == 403
        assert json.loads(body_no_cap)["error"]["code"] == "request_rejected"

        # Reject bad Host (421)
        status_bad_host, _, _ = await _raw_get(
            host,
            "/api/v1/sessions/alpha/stream",
            capability=token,
            host_header="evil.example:80",
        )
        assert status_bad_host == 421

        # Reject missing session before opening SSE (404)
        status_missing, _, body_missing = await _raw_get(
            host, "/api/v1/sessions/missing/stream", capability=token
        )
        assert status_missing == 404
        assert json.loads(body_missing)["error"]["code"] == "session_not_running"

        # Authorized stream emits sequenced telemetry + correlated diagnostic event
        status_ok, headers_ok, body_ok = await _raw_get(
            host, "/api/v1/sessions/alpha/stream", capability=token
        )
        assert status_ok == 200
        assert headers_ok["content-type"] == "text/event-stream; charset=utf-8"
        assert headers_ok["cache-control"] == "no-store, max-age=0"

        events = _parse_sse(body_ok.decode("utf-8"))
        telemetry_events = [item for item in events if item["event"] == "telemetry"]
        diagnostic_events = [item for item in events if item["event"] == "diagnostic"]

        assert [item["data"]["sequence_number"] for item in telemetry_events] == [1, 2]
        assert telemetry_events[0]["data"]["session"] == "alpha"
        assert len(diagnostic_events) == 1
        assert diagnostic_events[0]["data"]["fault_code"] == "OPERATION_DEADLINE_EXCEEDED"
        assert (
            diagnostic_events[0]["data"]["correlation_id"]
            == telemetry_events[1]["data"]["correlation_id"]
        )
    finally:
        await host.close()


async def _raw_get(
    host: StudioHost,
    path: str,
    *,
    capability: str | None = None,
    host_header: str | None = None,
) -> tuple[int, dict[str, str], bytes]:
    reader, writer = await asyncio.open_connection(*host.address)
    header_host = host_header or f"{host.address[0]}:{host.address[1]}"
    lines = [f"GET {path} HTTP/1.1", f"Host: {header_host}"]
    if capability is not None:
        lines.append(f"{CAPABILITY_HEADER}: {capability}")
    lines.append("Connection: close")
    writer.write(("\r\n".join(lines) + "\r\n\r\n").encode("ascii"))
    await writer.drain()
    raw = await reader.read()
    writer.close()
    await writer.wait_closed()
    head, _, body = raw.partition(b"\r\n\r\n")
    head_lines = head.decode("ascii").split("\r\n")
    status = int(head_lines[0].split(" ")[1])
    headers: dict[str, str] = {}
    for line in head_lines[1:]:
        key, _, val = line.partition(":")
        headers[key.strip().lower()] = val.strip()
    return status, headers, body


class _SseEvent(TypedDict):
    event: str
    id: str
    data: dict[str, object]


def _parse_sse(text: str) -> list[_SseEvent]:
    parsed: list[_SseEvent] = []
    for block in text.strip().split("\n\n"):
        if not block.strip():
            continue
        event_name = ""
        event_id = ""
        data_json = ""
        for line in block.splitlines():
            if line.startswith("event: "):
                event_name = line.removeprefix("event: ")
            elif line.startswith("id: "):
                event_id = line.removeprefix("id: ")
            elif line.startswith("data: "):
                data_json = line.removeprefix("data: ")
        parsed.append(
            {
                "event": event_name,
                "id": event_id,
                "data": cast(dict[str, object], json.loads(data_json)),
            }
        )
    return parsed
