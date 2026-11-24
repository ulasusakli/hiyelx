"""Bounded telemetry buffering, fault taxonomy, and SSE framing for Studio P7."""

from __future__ import annotations

import json
import time
from collections import deque
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Final

from hiyelx.simulation import SimulationPreviewSnapshot

TELEMETRY_SCHEMA_VERSION: Final = "1"
DEFAULT_TELEMETRY_BUFFER_LIMIT: Final = 256
DEFAULT_TELEMETRY_SAMPLE_HZ: Final = 2.0


@dataclass(frozen=True, slots=True)
class FaultDiagnosis:
    """Deterministic best-effort fault diagnosis for Studio Diagnostics (M11)."""

    fault_code: str
    severity: str
    title: str
    likely_causes: tuple[str, ...]
    recommended_checks: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class TelemetryFrame:
    """One sequenced, timestamped telemetry sample emitted over SSE."""

    schema_version: str
    session: str
    sequence_number: int
    timestamp_monotonic_ms: float
    timestamp_utc: str
    sampling_rate_hz: float
    buffer_limit: int
    dropped_frames: int
    correlation_id: str
    runtime_state: str
    resources: tuple[Mapping[str, object], ...]

    def to_document(self) -> dict[str, object]:
        return {
            "buffer_limit": self.buffer_limit,
            "correlation_id": self.correlation_id,
            "dropped_frames": self.dropped_frames,
            "resources": list(self.resources),
            "runtime_state": self.runtime_state,
            "sampling_rate_hz": self.sampling_rate_hz,
            "schema_version": self.schema_version,
            "sequence_number": self.sequence_number,
            "session": self.session,
            "timestamp_monotonic_ms": self.timestamp_monotonic_ms,
            "timestamp_utc": self.timestamp_utc,
        }


@dataclass(frozen=True, slots=True)
class StructuredLogRecord:
    """One structured diagnostic/log entry correlated to a stream frame or fault."""

    schema_version: str
    sequence_number: int
    timestamp_utc: str
    level: str
    source: str
    correlation_id: str
    fault_code: str | None
    message: str

    def to_document(self) -> dict[str, object]:
        return {
            "correlation_id": self.correlation_id,
            "fault_code": self.fault_code,
            "level": self.level,
            "message": self.message,
            "schema_version": self.schema_version,
            "sequence_number": self.sequence_number,
            "source": self.source,
            "timestamp_utc": self.timestamp_utc,
        }


class BoundedTelemetryRingBuffer[T]:
    """Fixed-capacity ring buffer with deterministic drop-oldest backpressure."""

    def __init__(self, capacity: int = DEFAULT_TELEMETRY_BUFFER_LIMIT) -> None:
        if capacity <= 0:
            msg = "buffer capacity must be positive"
            raise ValueError(msg)
        self._capacity = capacity
        self._items: deque[T] = deque()
        self._dropped_count = 0

    @property
    def capacity(self) -> int:
        return self._capacity

    @property
    def dropped_count(self) -> int:
        return self._dropped_count

    def __len__(self) -> int:
        return len(self._items)

    def push(self, item: T) -> bool:
        """Append one item, dropping the oldest if at capacity.

        Returns True if an older item was dropped due to backpressure.
        """
        dropped = False
        if len(self._items) >= self._capacity:
            self._items.popleft()
            self._dropped_count += 1
            dropped = True
        self._items.append(item)
        return dropped

    def snapshot(self) -> tuple[T, ...]:
        return tuple(self._items)


def classify_fault(reason: str) -> FaultDiagnosis:
    """Map sanitized Runtime health/error strings to actionable best-effort diagnostics."""
    normalized = reason.strip().lower()
    if "deadline exceeded" in normalized:
        return FaultDiagnosis(
            fault_code="OPERATION_DEADLINE_EXCEEDED",
            severity="error",
            title="Runtime operation deadline exceeded",
            likely_causes=(
                "Backend driver or device I/O blocked longer than the configured RB-1 deadline.",
                "Host CPU contention or stalled serial/bus response.",
            ),
            recommended_checks=(
                "Inspect Runtime event history for the resource correlation ID.",
                "Verify driver timeout policy and device responsiveness before restarting.",
            ),
        )
    if "backend unavailable" in normalized:
        return FaultDiagnosis(
            fault_code="BACKEND_UNAVAILABLE",
            severity="error",
            title="Resource backend unavailable",
            likely_causes=(
                "Underlying device disconnected or driver initialization failed.",
                "OS permission error on serial/USB/CAN interface.",
            ),
            recommended_checks=(
                "Check Runtime process logs and physical device connection.",
                "Run device preflight checks before re-enabling the component.",
            ),
        )
    if "safe-stop failed" in normalized:
        return FaultDiagnosis(
            fault_code="SAFE_STOP_FAILED",
            severity="error",
            title="Best-effort software safe-stop failed",
            likely_causes=(
                "Actuator stopped responding during shutdown or safe-stop command.",
                "Bus link dropped before zero-velocity command was acknowledged.",
            ),
            recommended_checks=(
                "Verify physical hardware is in a safe state using external hardware E-stop.",
                "Inspect fault events before powering or commanding actuators again.",
            ),
        )
    if "session_not_running" in normalized or "session stopped" in normalized:
        return FaultDiagnosis(
            fault_code="RUNTIME_SESSION_STOPPED",
            severity="warning",
            title="Observed Runtime session stopped",
            likely_causes=(
                "The foreground `hiyelx runtime start` process exited or was stopped.",
            ),
            recommended_checks=(
                "Start a new local session or select another active session.",
            ),
        )
    return FaultDiagnosis(
        fault_code="RUNTIME_DIAGNOSTIC_WARNING",
        severity="warning",
        title="Runtime diagnostic condition reported",
        likely_causes=("Sanitized runtime condition or transient observation failure.",),
        recommended_checks=("Review structured logs and Runtime health snapshot.",),
    )


def build_telemetry_frame(
    *,
    session: str,
    snapshot: SimulationPreviewSnapshot,
    sequence_number: int,
    sampling_rate_hz: float,
    buffer_limit: int = DEFAULT_TELEMETRY_BUFFER_LIMIT,
    dropped_frames: int = 0,
    correlation_id: str | None = None,
) -> TelemetryFrame:
    """Build one canonical schema-v1 TelemetryFrame from a SimulationPreviewSnapshot."""
    now_mono_ms = round(time.monotonic() * 1000.0, 3)
    now_utc = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    corr = correlation_id or f"{session}-seq-{sequence_number}"
    resources = tuple(
        {
            "health_status": resource.health_status.value,
            "health_summary": resource.health_summary,
            "identity": resource.identity.value,
            "kind": resource.kind,
            "lifecycle_state": resource.lifecycle_state.value,
            "state": {
                "angular_position_radians": resource.state.angular_position_radians,
                "angular_velocity_radians_per_second": (
                    resource.state.angular_velocity_radians_per_second
                ),
                "revision": resource.state.revision,
                "simulation_time_seconds": resource.state.simulation_time_seconds,
            },
        }
        for resource in snapshot.resources
    )
    return TelemetryFrame(
        schema_version=TELEMETRY_SCHEMA_VERSION,
        session=session,
        sequence_number=sequence_number,
        timestamp_monotonic_ms=now_mono_ms,
        timestamp_utc=now_utc,
        sampling_rate_hz=sampling_rate_hz,
        buffer_limit=buffer_limit,
        dropped_frames=dropped_frames,
        correlation_id=corr,
        runtime_state=snapshot.runtime_state.value,
        resources=resources,
    )


def format_sse_event(
    event: str,
    event_id: int,
    payload: Mapping[str, object],
) -> bytes:
    """Encode one compact UTF-8 Server-Sent Events frame."""
    encoded = json.dumps(
        payload,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return f"id: {event_id}\nevent: {event}\ndata: {encoded}\n\n".encode()
