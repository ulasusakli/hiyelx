import asyncio
import json
import os
import shutil
import signal
import socket
import sqlite3
import stat
import tempfile
import time
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

import pytest

from hiyelx.config import ResourceDefinition, RuntimeConfig
from hiyelx.models import ModelRegistry
from hiyelx.resources import HealthStatus, LifecycleState, ResourceIdentity
from hiyelx.runtime import (
    RuntimeEvent,
    RuntimeEventOperation,
    RuntimeEventOutcome,
    RuntimeManagerState,
    RuntimeOperationsSnapshot,
    RuntimeResourceSnapshot,
    control,
    history,
)
from hiyelx.runtime.control import (
    MAX_MESSAGE_BYTES,
    MAX_PREVIEW_RESOURCES,
    MIN_PREVIEW_RESOURCES,
    PREVIEW_REQUEST_TIMEOUT_SECONDS,
    PROTOCOL_VERSION,
    STATE_DIRECTORY_ENV,
    ControlCommand,
    ControlErrorCode,
    ControlProtocolError,
    ControlRequest,
    FailureReply,
    InvalidSessionIdError,
    PreviewReply,
    ResourceStatus,
    RuntimePreviewUnavailableError,
    RuntimePreviewUnsupportedError,
    SessionAlreadyRunningError,
    SessionNotRunningError,
    StatusReply,
    StopCoordinator,
    StopReply,
    UnknownControlCommandError,
    UnsafeSessionPathError,
    UnsupportedPlatformError,
    UnsupportedRuntimeModelError,
    configuration_fingerprint,
    decode_reply,
    decode_request,
    encode_reply,
    encode_request,
    render_status,
    request_preview,
    reserve_session,
    resolve_state_directory,
    run_local_runtime,
    status_reply,
    validate_session_id,
    validate_simulation_config,
)
from hiyelx.runtime.history import (
    HistoryStoreError,
    RunResult,
    StopReason,
    list_events,
    list_runs,
)
from hiyelx.runtime.operations import RuntimeOperations
from hiyelx.simulation import (
    SimulationMotorPreviewState,
    SimulationPreviewResourceSnapshot,
    SimulationPreviewSnapshot,
    SimulationPreviewUnavailableError,
    UnsupportedSimulationPreviewResourceError,
    register_simulated_motor,
)


@pytest.mark.parametrize(
    "session",
    ("alpha", "alpha-2", "alpha_2", "a" * 48, "0-alpha"),
)
def test_session_id_accepts_only_canonical_safe_values(session: str) -> None:
    assert validate_session_id(session) == session


@pytest.mark.parametrize(
    "session",
    ("", "A", "alpha.beta", "../alpha", "alpha/beta", "alpha beta", "é", "a" * 49),
)
def test_session_id_rejects_unsafe_values(session: str) -> None:
    with pytest.raises(InvalidSessionIdError):
        validate_session_id(session)


def test_state_directory_resolution_is_explicit_and_platform_bounded(
    tmp_path: Path,
) -> None:
    override = tmp_path / "state"
    assert resolve_state_directory({STATE_DIRECTORY_ENV: str(override)}) == override
    default = resolve_state_directory({})
    assert default.name == f"hiyelx-runtime-{os.geteuid()}"

    with pytest.raises(UnsafeSessionPathError):
        resolve_state_directory({STATE_DIRECTORY_ENV: "relative"})
    with pytest.raises(UnsupportedPlatformError):
        resolve_state_directory({}, platform="win32")


def test_reservation_and_atomic_manifest_are_private_and_minimal(
    tmp_path: Path,
) -> None:
    state = tmp_path / "state"
    owned = reserve_session("alpha", state_directory=state)
    fingerprint = configuration_fingerprint(_simulation_config())
    try:
        owned.publish(fingerprint)
        layout = owned.layout
        assert stat.S_IMODE(state.stat().st_mode) == 0o700
        assert stat.S_IMODE(layout.directory.stat().st_mode) == 0o700
        assert stat.S_IMODE(layout.lock.stat().st_mode) == 0o600
        assert stat.S_IMODE(layout.manifest.stat().st_mode) == 0o600
        assert not layout.manifest_temp.exists()

        document = json.loads(layout.manifest.read_text(encoding="utf-8"))
        assert document == {
            "config_fingerprint": fingerprint,
            "owner_uid": os.geteuid(),
            "pid": os.getpid(),
            "protocol_version": PROTOCOL_VERSION,
            "session": "alpha",
        }
        assert "credential" not in repr(document)
        assert "settings" not in repr(document)
    finally:
        assert owned.cleanup(final=True)


def test_symlinked_state_or_session_path_is_rejected(tmp_path: Path) -> None:
    target = tmp_path / "target"
    target.mkdir(mode=0o700)
    state_link = tmp_path / "state"
    state_link.symlink_to(target, target_is_directory=True)
    with pytest.raises(UnsafeSessionPathError):
        reserve_session("alpha", state_directory=state_link)

    state = tmp_path / "real-state"
    state.mkdir(mode=0o700)
    (state / "alpha").symlink_to(target, target_is_directory=True)
    with pytest.raises(UnsafeSessionPathError):
        reserve_session("alpha", state_directory=state)


def test_active_session_is_refused_and_stale_artifacts_are_reclaimed(
    short_state_directory: Path,
) -> None:
    state = short_state_directory
    first = reserve_session("alpha", state_directory=state)
    try:
        active_before = _artifact_snapshot(first.layout.directory)
        with pytest.raises(SessionAlreadyRunningError):
            reserve_session("alpha", state_directory=state)
        assert _artifact_snapshot(first.layout.directory) == active_before
    finally:
        assert first.cleanup(final=True)

    stale = state / "stale"
    stale.mkdir(mode=0o700)
    (stale / "owner.lock").write_bytes(b"")
    os.chmod(stale / "owner.lock", 0o600)
    stale_socket = socket.socket(socket.AF_UNIX)
    try:
        stale_socket.bind(str(stale / "control.sock"))
    finally:
        stale_socket.close()
    os.chmod(stale / "control.sock", 0o600)
    (stale / "manifest.json").write_text("stale", encoding="utf-8")
    os.chmod(stale / "manifest.json", 0o600)

    replacement = reserve_session("stale", state_directory=state)
    try:
        assert not replacement.layout.socket.exists()
        assert not replacement.layout.manifest.exists()
    finally:
        assert replacement.cleanup(final=True)


def test_ambiguous_owned_cleanup_preserves_every_entry(
    short_state_directory: Path,
) -> None:
    owned = reserve_session("ambiguous", state_directory=short_state_directory)
    owned.publish(configuration_fingerprint(_simulation_config()))
    owned_socket = socket.socket(socket.AF_UNIX)
    try:
        owned_socket.bind(str(owned.layout.socket))
    finally:
        owned_socket.close()
    os.chmod(owned.layout.socket, 0o600)
    temporary = owned.layout.manifest_temp
    temporary.write_text("temporary", encoding="utf-8")
    os.chmod(temporary, 0o600)
    unrelated = owned.layout.directory / "unrelated.txt"
    unrelated.write_text("keep", encoding="utf-8")
    os.chmod(unrelated, 0o600)
    before = _artifact_snapshot(owned.layout.directory)

    assert not owned.cleanup(final=True)

    assert _artifact_snapshot(owned.layout.directory) == before


def test_ambiguous_stale_reclamation_preserves_every_entry(
    short_state_directory: Path,
) -> None:
    stale = short_state_directory / "ambiguous-stale"
    stale.mkdir(mode=0o700)
    (stale / "owner.lock").write_bytes(b"")
    (stale / "manifest.json").write_text("stale", encoding="utf-8")
    (stale / ".manifest.tmp").write_text("temporary", encoding="utf-8")
    unrelated = stale / "unrelated.txt"
    unrelated.write_text("keep", encoding="utf-8")
    stale_socket = socket.socket(socket.AF_UNIX)
    try:
        stale_socket.bind(str(stale / "control.sock"))
    finally:
        stale_socket.close()
    for path in stale.iterdir():
        os.chmod(path, 0o600, follow_symlinks=False)
    before = _artifact_snapshot(stale)

    with pytest.raises(UnsafeSessionPathError):
        reserve_session("ambiguous-stale", state_directory=short_state_directory)

    assert _artifact_snapshot(stale) == before


@pytest.mark.parametrize("ambiguity", ("wrong-type", "symlink", "permissions"))
def test_stale_preflight_rejects_unsafe_entries_without_mutation(
    ambiguity: str,
    short_state_directory: Path,
) -> None:
    stale = short_state_directory / f"unsafe-{ambiguity}"
    stale.mkdir(mode=0o700)
    lock = stale / "owner.lock"
    lock.write_bytes(b"")
    lock.chmod(0o600)
    ambiguous = stale / ("control.sock" if ambiguity == "wrong-type" else "manifest.json")
    if ambiguity == "symlink":
        target = short_state_directory / "target"
        target.write_text("keep", encoding="utf-8")
        target.chmod(0o600)
        ambiguous.symlink_to(target)
    else:
        ambiguous.write_text("keep", encoding="utf-8")
        ambiguous.chmod(0o644 if ambiguity == "permissions" else 0o600)
    before = _artifact_snapshot(stale)

    with pytest.raises(UnsafeSessionPathError):
        reserve_session(stale.name, state_directory=short_state_directory)

    assert _artifact_snapshot(stale) == before


def test_cleanup_retries_transient_failure_and_never_removes_unrelated_path(
    short_state_directory: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = short_state_directory
    owned = reserve_session("alpha", state_directory=state)
    owned.publish(configuration_fingerprint(_simulation_config()))
    original_unlink = control.os.unlink
    failed_once = False

    def transient_unlink(path: os.PathLike[str] | str) -> None:
        nonlocal failed_once
        if Path(path).name == "manifest.json" and not failed_once:
            failed_once = True
            raise OSError
        original_unlink(path)

    monkeypatch.setattr(control.os, "unlink", transient_unlink)
    assert not owned.cleanup()
    assert owned.cleanup()
    assert not owned.layout.directory.exists()

    guarded = reserve_session("guarded", state_directory=state)
    unrelated = guarded.layout.directory / "unrelated.txt"
    unrelated.write_text("keep", encoding="utf-8")
    os.chmod(unrelated, 0o600)
    assert not guarded.cleanup(final=True)
    assert unrelated.read_text(encoding="utf-8") == "keep"


def test_protocol_round_trips_are_deterministic_and_strict() -> None:
    request = ControlRequest(ControlCommand.STATUS, "alpha")
    assert encode_request(request) == encode_request(request)
    assert decode_request(encode_request(request)) == request

    reply = _status()
    assert decode_reply(encode_reply(reply)) == reply
    stop = StopReply("alpha")
    assert decode_reply(encode_reply(stop)) == stop
    failure = FailureReply(
        ControlErrorCode.INVALID_REQUEST,
        "control request is invalid",
    )
    assert decode_reply(encode_reply(failure)) == failure

    malformed = b'{"protocol_version":1}\n'
    with pytest.raises(ControlProtocolError):
        decode_request(malformed)
    with pytest.raises(ControlProtocolError):
        decode_request(b"x" * (MAX_MESSAGE_BYTES + 1) + b"\n")
    unknown = (
        b'{"command":"unknown","protocol_version":1,"session":"alpha"}\n'
    )
    with pytest.raises(UnknownControlCommandError):
        decode_request(unknown)
    arbitrary = (
        b'{"error":{"code":"invalid_request","message":"/dev/private secret"},'
        b'"ok":false,"protocol_version":1}\n'
    )
    with pytest.raises(ControlProtocolError):
        decode_reply(arbitrary)
    unsafe_status = StatusReply(
        session="alpha",
        manager_state=RuntimeManagerState.RUNNING,
        resources=(
            ResourceStatus(
                ResourceIdentity("sim_motor"),
                LifecycleState.RUNNING,
                HealthStatus.UNHEALTHY,
                "device=/dev/private credential=top-secret",
            ),
        ),
        successful_start_order=(ResourceIdentity("sim_motor"),),
        active_resource_order=(ResourceIdentity("sim_motor"),),
        event_high_water_mark=3,
        latest_event_summary="runtime running",
    )
    with pytest.raises(ControlProtocolError):
        encode_reply(unsafe_status)


def test_preview_protocol_round_trip_is_exact_bounded_and_strict() -> None:
    request = ControlRequest(ControlCommand.PREVIEW, "alpha")
    encoded_request = encode_request(request)
    assert encoded_request == (
        b'{"command":"preview","protocol_version":1,"session":"alpha"}\n'
    )
    assert decode_request(encoded_request) == request

    reply = _preview_reply()
    encoded_reply = encode_reply(reply)
    assert encoded_reply == (
        b'{"kind":"preview","ok":true,"protocol_version":1,"result":{'
        b'"preview":{"resources":[{"health_status":"healthy",'
        b'"health_summary":null,"identity":"sim_motor","kind":"motor",'
        b'"lifecycle_state":"running","state":{'
        b'"angular_position_radians":0.0,'
        b'"angular_velocity_radians_per_second":0.0,"revision":0,'
        b'"simulation_time_seconds":0.0}}],"runtime_state":"running",'
        b'"schema_version":"1"},"session":"alpha"}}\n'
    )
    assert len(encoded_reply) <= MAX_MESSAGE_BYTES
    assert decode_reply(encoded_reply) == reply
    assert MIN_PREVIEW_RESOURCES == MAX_PREVIEW_RESOURCES == 1
    assert PREVIEW_REQUEST_TIMEOUT_SECONDS == 3.0


@pytest.mark.parametrize(
    "mutation",
    (
        "extra-result",
        "zero-resources",
        "multiple-resources",
        "boolean-revision",
        "integer-position",
        "unknown-runtime-state",
        "unsafe-health-summary",
    ),
)
def test_preview_reply_rejects_noncanonical_nested_values(mutation: str) -> None:
    document = json.loads(encode_reply(_preview_reply()))
    result = document["result"]
    preview = result["preview"]
    resources = preview["resources"]
    resource = resources[0]
    state = resource["state"]

    if mutation == "extra-result":
        result["extra"] = None
    elif mutation == "zero-resources":
        preview["resources"] = []
    elif mutation == "multiple-resources":
        preview["resources"] = [resource, resource.copy()]
    elif mutation == "boolean-revision":
        state["revision"] = True
    elif mutation == "integer-position":
        state["angular_position_radians"] = 0
    elif mutation == "unknown-runtime-state":
        preview["runtime_state"] = "private-state"
    else:
        resource["health_summary"] = "device=/dev/private credential=secret"

    message = json.dumps(
        document,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8") + b"\n"
    with pytest.raises(ControlProtocolError):
        decode_reply(message)


def test_preview_reply_rejects_nested_duplicate_keys() -> None:
    message = encode_reply(_preview_reply()).replace(
        b'"revision":0',
        b'"revision":0,"revision":0',
    )

    with pytest.raises(ControlProtocolError):
        decode_reply(message)


@pytest.mark.asyncio
async def test_preview_total_deadline_cancels_the_single_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cancelled = False

    async def never_returns(
        _session: str,
        _command: ControlCommand,
        *,
        state_directory: Path | None,
    ) -> control.ControlReply:
        del state_directory
        nonlocal cancelled
        try:
            await asyncio.Event().wait()
        finally:
            cancelled = True
        raise AssertionError("unreachable")

    monkeypatch.setattr(control, "PREVIEW_REQUEST_TIMEOUT_SECONDS", 0.01)
    monkeypatch.setattr(control, "_request", never_returns)

    with pytest.raises(ControlProtocolError):
        await request_preview("alpha")

    assert cancelled


@pytest.mark.parametrize("version", (True, False, 1.0, "1", None))
def test_request_protocol_version_requires_exact_integer(version: object) -> None:
    message = json.dumps(
        {"command": "status", "protocol_version": version, "session": "alpha"},
        separators=(",", ":"),
    ).encode("ascii") + b"\n"

    with pytest.raises(ControlProtocolError):
        decode_request(message)


@pytest.mark.parametrize("version", (True, False, 1.0))
def test_response_protocol_version_requires_exact_integer(version: object) -> None:
    message = json.dumps(
        {
            "kind": "stop",
            "ok": True,
            "protocol_version": version,
            "result": {"session": "alpha", "stopped": True},
        },
        separators=(",", ":"),
    ).encode("ascii") + b"\n"

    with pytest.raises(ControlProtocolError):
        decode_reply(message)


@pytest.mark.parametrize(
    "message",
    (
        b'{"command":"status","command":"status","protocol_version":1,'
        b'"session":"alpha"}\n',
        b'{"command":"status","protocol_version":1,"protocol_version":1,'
        b'"session":"alpha"}\n',
        b'{"command":"status","protocol_version":1,"session":"alpha",'
        b'"session":"alpha"}\n',
    ),
    ids=("command", "version", "session"),
)
def test_request_duplicate_keys_are_rejected(message: bytes) -> None:
    with pytest.raises(ControlProtocolError):
        decode_request(message)


@pytest.mark.parametrize(
    "message",
    (
        b'{"kind":"stop","ok":true,"protocol_version":1,'
        b'"protocol_version":1,"result":{"session":"alpha","stopped":true}}\n',
        b'{"kind":"stop","ok":true,"protocol_version":1,'
        b'"result":{"session":"alpha","session":"alpha","stopped":true}}\n',
        b'{"error":{"code":"invalid_request","code":"invalid_request",'
        b'"message":"control request is invalid"},"ok":false,'
        b'"protocol_version":1}\n',
        b'{"kind":"stop","ok":true,"protocol_version":1,'
        b'"result":{"extra":1,"extra":2,"session":"alpha","stopped":true}}\n',
    ),
    ids=("top-level-version", "result-session", "failure-code", "unknown-field"),
)
def test_response_duplicate_keys_are_rejected(message: bytes) -> None:
    with pytest.raises(ControlProtocolError):
        decode_reply(message)


def test_request_extra_field_is_rejected() -> None:
    with pytest.raises(ControlProtocolError):
        decode_request(
            b'{"command":"status","extra":null,"protocol_version":1,'
            b'"session":"alpha"}\n'
        )


def test_request_wrong_primitive_type_is_rejected() -> None:
    with pytest.raises(ControlProtocolError):
        decode_request(b'{"command":1,"protocol_version":1,"session":"alpha"}\n')


def test_request_unsupported_integer_version_is_rejected() -> None:
    with pytest.raises(ControlProtocolError):
        decode_request(
            b'{"command":"status","protocol_version":2,"session":"alpha"}\n'
        )


def test_request_wrong_session_is_rejected() -> None:
    with pytest.raises(ControlProtocolError):
        decode_request(
            b'{"command":"status","protocol_version":1,"session":"../alpha"}\n'
        )


def test_snapshot_projection_and_canonical_status_are_sanitized() -> None:
    identity = ResourceIdentity("sim_motor")
    event = RuntimeEvent(
        sequence=3,
        operation=RuntimeEventOperation.RUNTIME_RUNNING,
        outcome=RuntimeEventOutcome.SUCCEEDED,
        summary="runtime running",
    )
    snapshot = RuntimeOperationsSnapshot(
        manager_state=RuntimeManagerState.RUNNING,
        resources=(
            RuntimeResourceSnapshot(
                identity,
                LifecycleState.RUNNING,
                HealthStatus.HEALTHY,
                None,
            ),
        ),
        startup_plan=(identity,),
        successful_start_order=(identity,),
        active_resource_order=(identity,),
        event_high_water_mark=3,
        events=(event,),
    )
    reply = status_reply("alpha", snapshot)

    assert render_status(reply) == (
        "session=alpha",
        "manager-state=running",
        "resource-count=1",
        "resource=sim_motor lifecycle=running health=healthy health-summary=none",
        "successful-start-order=sim_motor",
        "active-resource-order=sim_motor",
        "event-high-water-mark=3",
        "latest-event=runtime running",
    )
    assert "/dev/" not in "\n".join(render_status(reply))


def test_zero_resource_status_is_explicit_and_deterministic() -> None:
    reply = StatusReply(
        session="empty",
        manager_state=RuntimeManagerState.RUNNING,
        resources=(),
        successful_start_order=(),
        active_resource_order=(),
        event_high_water_mark=1,
        latest_event_summary="runtime running",
    )
    assert render_status(reply) == (
        "session=empty",
        "manager-state=running",
        "resource-count=0",
        "successful-start-order=",
        "active-resource-order=",
        "event-high-water-mark=1",
        "latest-event=runtime running",
    )


@pytest.mark.asyncio
async def test_stop_coordination_is_single_and_idempotent() -> None:
    coordinator = StopCoordinator()
    first = asyncio.create_task(coordinator.request_stop())
    second = asyncio.create_task(coordinator.request_stop())
    await coordinator.requested.wait()
    reply = StopReply("alpha")
    coordinator.complete(reply)
    coordinator.complete(FailureReply(ControlErrorCode.INTERNAL_FAILURE, "ignored"))

    assert await first == reply
    assert await second == reply
    assert coordinator.completed


@pytest.mark.asyncio
async def test_preview_socket_round_trip_is_read_only_and_disconnect_safe(
    short_state_directory: Path,
) -> None:
    registry = ModelRegistry()
    register_simulated_motor(registry)
    operations = RuntimeOperations(_simulation_config(), registry)
    await operations.start()
    owned = reserve_session("preview", state_directory=short_state_directory)
    server = control.LocalControlServer(owned.layout, operations, StopCoordinator())
    try:
        await server.start()
        owned.publish(configuration_fingerprint(_simulation_config()))
        operations_before = operations.snapshot()
        preview_before = operations.simulation_preview_snapshot()
        manifest_before = owned.layout.manifest.read_bytes()

        first = await request_preview(
            "preview",
            state_directory=short_state_directory,
        )
        second = await request_preview(
            "preview",
            state_directory=short_state_directory,
        )

        assert first == second
        assert first.session == "preview"
        assert first.preview == preview_before
        assert operations.snapshot() == operations_before
        assert operations.simulation_preview_snapshot() == preview_before
        assert owned.layout.manifest.read_bytes() == manifest_before

        _reader, disconnected = await asyncio.open_unix_connection(
            str(owned.layout.socket),
            limit=MAX_MESSAGE_BYTES + 1,
        )
        disconnected.write(
            encode_request(ControlRequest(ControlCommand.PREVIEW, "preview"))
        )
        await disconnected.drain()
        disconnected.transport.abort()

        status = await control.request_status(
            "preview",
            state_directory=short_state_directory,
        )
        assert status.manager_state is RuntimeManagerState.RUNNING
        assert operations.snapshot() == operations_before
        assert operations.simulation_preview_snapshot() == preview_before
    finally:
        await server.close()
        await server.wait_handlers()
        await operations.safe_stop()
        await operations.shutdown()
        assert owned.cleanup(final=True)


@pytest.mark.parametrize(
    "failure",
    ("unavailable", "unsupported-zero", "unsupported-multiple", "unsupported-kind"),
)
@pytest.mark.asyncio
async def test_preview_socket_maps_typed_provider_failures(
    failure: str,
    short_state_directory: Path,
) -> None:
    class FailingPreviewOperations:
        def simulation_preview_snapshot(self) -> SimulationPreviewSnapshot:
            if failure == "unavailable":
                raise SimulationPreviewUnavailableError
            if failure == "unsupported-kind":
                raise UnsupportedSimulationPreviewResourceError(
                    ResourceIdentity("unsupported")
                )
            resources = ()
            if failure == "unsupported-multiple":
                resources = (
                    _preview_resource("sim_motor"),
                    _preview_resource("sim_motor_2"),
                )
            return SimulationPreviewSnapshot(
                schema_version="1",
                runtime_state=RuntimeManagerState.RUNNING,
                resources=resources,
            )

    session = {
        "unavailable": "p-u",
        "unsupported-zero": "p-z",
        "unsupported-multiple": "p-m",
        "unsupported-kind": "p-k",
    }[failure]
    owned = reserve_session(session, state_directory=short_state_directory)
    server = control.LocalControlServer(
        owned.layout,
        cast(RuntimeOperations, FailingPreviewOperations()),
        StopCoordinator(),
    )
    try:
        await server.start()
        owned.publish(configuration_fingerprint(_simulation_config()))
        expected = (
            RuntimePreviewUnavailableError
            if failure == "unavailable"
            else RuntimePreviewUnsupportedError
        )
        expected_message = (
            "runtime preview is unavailable"
            if failure == "unavailable"
            else "runtime preview is unsupported"
        )
        with pytest.raises(expected) as caught:
            await request_preview(
                session,
                state_directory=short_state_directory,
            )
        assert str(caught.value) == expected_message
    finally:
        await server.close()
        await server.wait_handlers()
        assert owned.cleanup(final=True)


@pytest.mark.asyncio
async def test_preview_encoder_failure_is_sanitized_and_owner_stays_responsive(
    short_state_directory: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry = ModelRegistry()
    register_simulated_motor(registry)
    operations = RuntimeOperations(_simulation_config(), registry)
    await operations.start()
    owned = reserve_session("preview-encode", state_directory=short_state_directory)
    server = control.LocalControlServer(owned.layout, operations, StopCoordinator())
    original_encode_reply = control.encode_reply

    def fail_preview_encoding(reply: control.ControlReply) -> bytes:
        if isinstance(reply, PreviewReply):
            raise RuntimeError("private encoder detail")
        return original_encode_reply(reply)

    monkeypatch.setattr(control, "encode_reply", fail_preview_encoding)
    try:
        await server.start()
        owned.publish(configuration_fingerprint(_simulation_config()))

        with pytest.raises(ControlProtocolError):
            await request_preview(
                "preview-encode",
                state_directory=short_state_directory,
            )

        status = await control.request_status(
            "preview-encode",
            state_directory=short_state_directory,
        )
        assert status.manager_state is RuntimeManagerState.RUNNING
    finally:
        await server.close()
        await server.wait_handlers()
        await operations.safe_stop()
        await operations.shutdown()
        assert owned.cleanup(final=True)


@pytest.mark.asyncio
async def test_safe_stop_failure_still_calls_allowed_shutdown_once() -> None:
    class FailingSafeStopOperations:
        def __init__(self) -> None:
            self.manager_state = RuntimeManagerState.RUNNING
            self.safe_stop_calls = 0
            self.shutdown_calls = 0

        def snapshot(self) -> RuntimeOperationsSnapshot:
            return cast(
                RuntimeOperationsSnapshot,
                type("Snapshot", (), {"manager_state": self.manager_state})(),
            )

        async def safe_stop(self) -> None:
            self.safe_stop_calls += 1
            raise RuntimeError("private backend detail")

        async def shutdown(self) -> None:
            self.shutdown_calls += 1
            self.manager_state = RuntimeManagerState.STOPPED

    fake = FailingSafeStopOperations()

    assert not await control._cleanup_operations(  # pyright: ignore[reportPrivateUsage]
        cast(RuntimeOperations, fake)
    )
    assert fake.safe_stop_calls == 1
    assert fake.shutdown_calls == 1


def test_simulation_model_allowlist_rejects_hardware_and_external_models() -> None:
    validate_simulation_config(_simulation_config())
    for model in ("motor.dynamixel.xl430_w250_t", "motor.external.private"):
        with pytest.raises(UnsupportedRuntimeModelError):
            validate_simulation_config(_config_for_model(model))
    with pytest.raises(control.UnsafeRuntimeIdentityError):
        validate_simulation_config(
            RuntimeConfig(
                schema_version="1",
                resources=[
                    ResourceDefinition(
                        identity=ResourceIdentity("credential=top-secret\nforged=line"),
                        model="motor.simulated",
                        settings={},
                    )
                ],
            )
        )


@pytest.mark.asyncio
async def test_hardware_model_is_rejected_before_runtime_construction(
    short_state_directory: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    constructed = False

    def forbidden_construction(*_args: object, **_kwargs: object) -> None:
        nonlocal constructed
        constructed = True

    monkeypatch.setattr(control, "RuntimeOperations", forbidden_construction)
    history_root = short_state_directory.parent / f"{short_state_directory.name}-history"
    with pytest.raises(UnsupportedRuntimeModelError):
        await run_local_runtime(
            _config_for_model("motor.dynamixel.xl430_w250_t"),
            "hardware",
            state_directory=short_state_directory,
            history_directory=history_root,
        )
    assert not constructed
    entries = await asyncio.to_thread(lambda: tuple(short_state_directory.iterdir()))
    assert entries == ()
    assert not history_root.exists()


@pytest.mark.asyncio
async def test_history_failure_prevents_runtime_construction_and_cleans_session(
    short_state_directory: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    constructed = False

    def fail_history(**_kwargs: object) -> None:
        raise HistoryStoreError("private sqlite detail")

    def forbidden_construction(*_args: object, **_kwargs: object) -> None:
        nonlocal constructed
        constructed = True

    monkeypatch.setattr(control, "open_writer", fail_history)
    monkeypatch.setattr(control, "RuntimeOperations", forbidden_construction)
    history_root = short_state_directory.parent / f"{short_state_directory.name}-history"
    with pytest.raises(control.RuntimeHistoryError):
        await run_local_runtime(
            _simulation_config(),
            "alpha",
            state_directory=short_state_directory,
            history_directory=history_root,
        )
    assert not constructed
    assert not (short_state_directory / "alpha").exists()


@pytest.mark.asyncio
async def test_successful_stop_finalizes_once(
    short_state_directory: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    history_root = short_state_directory.parent / f"{short_state_directory.name}-history-once"
    finalize_calls = 0
    original_finalize = control.HistoryStore.finalize_run

    class LocalStopServer:
        def __init__(
            self,
            _layout: object,
            _operations: object,
            coordinator: StopCoordinator,
        ) -> None:
            self._coordinator = coordinator

        async def start(self) -> None:
            self._coordinator.stop_reason = StopReason.CLI_STOP
            self._coordinator.requested.set()

        def stop_accepting(self) -> None:
            pass

        async def wait_handlers(self) -> None:
            pass

        async def close(self) -> None:
            pass

    def count_finalize(
        store: control.HistoryStore,
        run_id: str,
        *,
        result: RunResult,
        stop_reason: StopReason,
        event_high_water_mark: int | None,
    ) -> object:
        nonlocal finalize_calls
        finalize_calls += 1
        return original_finalize(
            store,
            run_id,
            result=result,
            stop_reason=stop_reason,
            event_high_water_mark=event_high_water_mark,
        )

    monkeypatch.setattr(control, "LocalControlServer", LocalStopServer)
    monkeypatch.setattr(control.HistoryStore, "finalize_run", count_finalize)
    await run_local_runtime(
        _simulation_config(),
        "successful-finalize",
        state_directory=short_state_directory,
        history_directory=history_root,
    )

    assert finalize_calls == 1
    record = list_runs(root=history_root)[0]
    assert record.result is RunResult.COMPLETED
    assert record.stop_reason is StopReason.CLI_STOP
    persisted = list_events(record.run_id, root=history_root)
    assert tuple(event.sequence for event in persisted) == tuple(range(12))
    assert tuple(event.event_type for event in persisted) == (
        RuntimeEventOperation.RUNTIME_START,
        RuntimeEventOperation.RESOURCE_START,
        RuntimeEventOperation.RESOURCE_START,
        RuntimeEventOperation.RUNTIME_RUNNING,
        RuntimeEventOperation.SAFE_STOP,
        RuntimeEventOperation.SAFE_STOP,
        RuntimeEventOperation.SAFE_STOP,
        RuntimeEventOperation.SAFE_STOP_CLEANUP,
        RuntimeEventOperation.RUNTIME_SHUTDOWN,
        RuntimeEventOperation.RESOURCE_SHUTDOWN,
        RuntimeEventOperation.RESOURCE_SHUTDOWN,
        RuntimeEventOperation.RUNTIME_STOPPED,
    )


@pytest.mark.asyncio
async def test_startup_event_persistence_failure_blocks_readiness_and_cleans_runtime(
    short_state_directory: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    history_root = (
        short_state_directory.parent / f"{short_state_directory.name}-history-start-events"
    )
    ready: list[str] = []
    persist_calls = 0

    def fail_persist(*_args: object, **_kwargs: object) -> None:
        nonlocal persist_calls
        persist_calls += 1
        raise HistoryStoreError("private sqlite detail")

    monkeypatch.setattr(control.HistoryStore, "persist_events", fail_persist)
    with pytest.raises(control.RuntimeHistoryError):
        await run_local_runtime(
            _simulation_config(),
            "startup-events",
            state_directory=short_state_directory,
            history_directory=history_root,
            ready=ready.append,
        )

    assert ready == []
    assert persist_calls == 1
    assert not (short_state_directory / "startup-events").exists()
    record = list_runs(root=history_root)[0]
    assert record.result is RunResult.HISTORY_FAILED
    assert record.stop_reason is StopReason.HISTORY_FAILURE
    assert record.event_high_water_mark is None
    assert list_events(record.run_id, root=history_root) == ()


@pytest.mark.asyncio
async def test_startup_event_clock_failure_rolls_back_and_finalizes_history_failed(
    short_state_directory: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    history_root = (
        short_state_directory.parent / f"{short_state_directory.name}-history-clock"
    )
    original_open_writer = control.open_writer
    original_cleanup = control._cleanup_operations  # pyright: ignore[reportPrivateUsage]
    clock_calls = 0
    cleanup_calls = 0
    ready: list[str] = []

    def fail_once_clock() -> datetime:
        nonlocal clock_calls
        clock_calls += 1
        if clock_calls == 2:
            raise RuntimeError("private clock failed")
        return datetime(2026, 10, 18, 10, 11, 12, 123456, tzinfo=UTC)

    def open_with_clock(*, root: Path | None = None) -> control.HistoryStore:
        return original_open_writer(root=root, clock=fail_once_clock)

    async def count_cleanup(
        operations: RuntimeOperations,
        *,
        persist_events: Callable[[], None] | None = None,
    ) -> bool:
        nonlocal cleanup_calls
        cleanup_calls += 1
        return await original_cleanup(operations, persist_events=persist_events)

    monkeypatch.setattr(control, "open_writer", open_with_clock)
    monkeypatch.setattr(control, "_cleanup_operations", count_cleanup)
    with pytest.raises(control.RuntimeHistoryError) as caught:
        await run_local_runtime(
            _simulation_config(),
            "event-clock",
            state_directory=short_state_directory,
            history_directory=history_root,
            ready=ready.append,
        )

    assert str(caught.value) == ""
    assert ready == []
    assert cleanup_calls == 1
    assert not (short_state_directory / "event-clock").exists()
    record = list_runs(root=history_root)[0]
    assert record.result is RunResult.HISTORY_FAILED
    assert record.stop_reason is StopReason.HISTORY_FAILURE
    assert record.ended_at is not None
    assert record.event_high_water_mark is None
    assert list_events(record.run_id, root=history_root) == ()


@pytest.mark.asyncio
async def test_termination_event_failure_preserves_committed_prefix_and_cleanup(
    short_state_directory: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    history_root = (
        short_state_directory.parent / f"{short_state_directory.name}-history-stop-events"
    )
    original_persist = control.HistoryStore.persist_events
    persist_calls = 0

    class LocalStopServer:
        def __init__(
            self,
            _layout: object,
            _operations: object,
            coordinator: StopCoordinator,
        ) -> None:
            self._coordinator = coordinator

        async def start(self) -> None:
            self._coordinator.request_local_stop()

        def stop_accepting(self) -> None:
            pass

        async def wait_handlers(self) -> None:
            pass

        async def close(self) -> None:
            pass

    def fail_second_persist(
        store: control.HistoryStore,
        *args: object,
        **kwargs: object,
    ) -> int | None:
        nonlocal persist_calls
        persist_calls += 1
        if persist_calls == 2:
            raise HistoryStoreError("private sqlite detail")
        return original_persist(store, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(control, "LocalControlServer", LocalStopServer)
    monkeypatch.setattr(control.HistoryStore, "persist_events", fail_second_persist)
    with pytest.raises(control.RuntimeHistoryError):
        await run_local_runtime(
            _simulation_config(),
            "termination-events",
            state_directory=short_state_directory,
            history_directory=history_root,
        )

    assert persist_calls == 2
    assert not (short_state_directory / "termination-events").exists()
    record = list_runs(root=history_root)[0]
    assert record.result is RunResult.HISTORY_FAILED
    assert record.stop_reason is StopReason.HISTORY_FAILURE
    assert record.event_high_water_mark == 3
    assert tuple(
        event.sequence for event in list_events(record.run_id, root=history_root)
    ) == (0, 1, 2, 3)


@pytest.mark.asyncio
async def test_cleanup_failure_precedes_secondary_event_persistence_failure(
    short_state_directory: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    history_root = (
        short_state_directory.parent
        / f"{short_state_directory.name}-history-cleanup-event-failure"
    )
    original_persist = control.HistoryStore.persist_events
    persist_calls = 0

    class LocalStopServer:
        def __init__(
            self,
            _layout: object,
            _operations: object,
            coordinator: StopCoordinator,
        ) -> None:
            self._coordinator = coordinator

        async def start(self) -> None:
            self._coordinator.request_local_stop()

        def stop_accepting(self) -> None:
            pass

        async def wait_handlers(self) -> None:
            pass

        async def close(self) -> None:
            pass

    def fail_second_persist(
        store: control.HistoryStore,
        *args: object,
        **kwargs: object,
    ) -> int | None:
        nonlocal persist_calls
        persist_calls += 1
        if persist_calls == 2:
            raise HistoryStoreError("private sqlite detail")
        return original_persist(store, *args, **kwargs)  # type: ignore[arg-type]

    async def fail_cleanup(
        _operations: RuntimeOperations,
        *,
        persist_events: Callable[[], None] | None = None,
    ) -> bool:
        if persist_events is not None:
            persist_events()
        return False

    monkeypatch.setattr(control, "LocalControlServer", LocalStopServer)
    monkeypatch.setattr(control.HistoryStore, "persist_events", fail_second_persist)
    monkeypatch.setattr(control, "_cleanup_operations", fail_cleanup)
    with pytest.raises(control.RuntimeOwnerCleanupError):
        await run_local_runtime(
            _simulation_config(),
            "cleanup-event-failure",
            state_directory=short_state_directory,
            history_directory=history_root,
        )

    assert persist_calls == 2
    record = list_runs(root=history_root)[0]
    assert record.result is RunResult.CLEANUP_FAILED
    assert record.stop_reason is StopReason.CLEANUP_FAILURE
    assert not (short_state_directory / "cleanup-event-failure").exists()


@pytest.mark.asyncio
async def test_startup_and_rollback_cleanup_failure_keeps_startup_precedence(
    short_state_directory: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    history_root = (
        short_state_directory.parent / f"{short_state_directory.name}-history-startup-cleanup"
    )

    class FailingStartupOperations:
        def __init__(self, *_args: object) -> None:
            self.safe_stop_calls = 0
            self.shutdown_calls = 0
            instances.append(self)

        async def start(self) -> None:
            raise RuntimeError("private startup detail")

        def snapshot(self) -> RuntimeOperationsSnapshot:
            return cast(
                RuntimeOperationsSnapshot,
                type(
                    "Snapshot",
                    (),
                    {
                        "manager_state": RuntimeManagerState.RUNNING,
                        "event_high_water_mark": None,
                    },
                )(),
            )

        async def safe_stop(self) -> None:
            self.safe_stop_calls += 1
            raise RuntimeError("private rollback detail")

        async def shutdown(self) -> None:
            self.shutdown_calls += 1
            raise RuntimeError("private rollback detail")

    instances: list[FailingStartupOperations] = []
    monkeypatch.setattr(control, "RuntimeOperations", FailingStartupOperations)
    with pytest.raises(control.RuntimeOwnerStartupError):
        await run_local_runtime(
            _simulation_config(),
            "startup-cleanup",
            state_directory=short_state_directory,
            history_directory=history_root,
        )

    assert len(instances) == 1
    assert instances[0].safe_stop_calls == 1
    assert instances[0].shutdown_calls == 1
    record = list_runs(root=history_root)[0]
    assert record.result is RunResult.STARTUP_FAILED
    assert record.stop_reason is StopReason.STARTUP_FAILURE


@pytest.mark.asyncio
async def test_pre_ready_control_server_failure_finalizes_startup_failed(
    short_state_directory: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    history_root = (
        short_state_directory.parent
        / f"{short_state_directory.name}-history-runtime-failure"
    )

    class FailingServer:
        def __init__(self, *_args: object) -> None:
            pass

        async def start(self) -> None:
            raise ControlProtocolError

        def stop_accepting(self) -> None:
            pass

        async def wait_handlers(self) -> None:
            pass

        async def close(self) -> None:
            pass

    monkeypatch.setattr(control, "LocalControlServer", FailingServer)
    with pytest.raises(control.RuntimeOwnerStartupError):
        await run_local_runtime(
            _simulation_config(),
            "runtime-failure",
            state_directory=short_state_directory,
            history_directory=history_root,
        )

    records = list_runs(root=history_root)
    assert len(records) == 1
    assert records[0].result is RunResult.STARTUP_FAILED
    assert records[0].stop_reason is StopReason.STARTUP_FAILURE
    assert not (short_state_directory / "runtime-failure").exists()


@pytest.mark.asyncio
async def test_startup_failure_persists_sanitized_snapshot_prefix(
    short_state_directory: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    history_root = (
        short_state_directory.parent
        / f"{short_state_directory.name}-history-startup-event-prefix"
    )
    identity = ResourceIdentity("sim_motor")
    events = (
        RuntimeEvent(
            0,
            RuntimeEventOperation.RUNTIME_START,
            RuntimeEventOutcome.REQUESTED,
            "runtime start requested",
        ),
        RuntimeEvent(
            1,
            RuntimeEventOperation.RESOURCE_START,
            RuntimeEventOutcome.ATTEMPTED,
            "resource start attempted",
            identity,
            LifecycleState.CREATED,
            HealthStatus.UNKNOWN,
        ),
        RuntimeEvent(
            2,
            RuntimeEventOperation.RESOURCE_START,
            RuntimeEventOutcome.FAILED,
            "resource start failed",
            identity,
            LifecycleState.FAILED,
            HealthStatus.UNHEALTHY,
        ),
    )

    class FailingStartupOperations:
        def __init__(self, *_args: object) -> None:
            pass

        async def start(self) -> None:
            raise RuntimeError("private startup detail")

        def snapshot(self) -> RuntimeOperationsSnapshot:
            return cast(
                RuntimeOperationsSnapshot,
                type(
                    "Snapshot",
                    (),
                    {
                        "manager_state": RuntimeManagerState.FAILED,
                        "event_high_water_mark": 2,
                        "events": events,
                    },
                )(),
            )

    monkeypatch.setattr(control, "RuntimeOperations", FailingStartupOperations)
    with pytest.raises(control.RuntimeOwnerStartupError):
        await run_local_runtime(
            _simulation_config(),
            "startup-event-prefix",
            state_directory=short_state_directory,
            history_directory=history_root,
        )

    record = list_runs(root=history_root)[0]
    assert record.result is RunResult.STARTUP_FAILED
    assert record.stop_reason is StopReason.STARTUP_FAILURE
    assert record.event_high_water_mark == 2
    persisted = list_events(record.run_id, root=history_root)
    assert tuple(event.sequence for event in persisted) == (0, 1, 2)
    assert tuple(event.summary for event in persisted) == tuple(
        event.summary for event in events
    )


@pytest.mark.asyncio
async def test_signal_handler_precedes_readiness_and_restores_on_startup_failure(
    short_state_directory: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    history_root = (
        short_state_directory.parent
        / f"{short_state_directory.name}-history-signal-readiness"
    )
    events: list[str] = []
    loop = asyncio.get_running_loop()
    original_publish = control.OwnedSession.publish

    def add_signal_handler(
        signum: signal.Signals,
        callback: object,
    ) -> None:
        assert signum is signal.SIGINT
        assert callable(callback)
        events.append("signal-installed")

    def remove_signal_handler(signum: signal.Signals) -> bool:
        assert signum is signal.SIGINT
        events.append("signal-restored")
        return True

    def publish(owned: control.OwnedSession, fingerprint: str) -> None:
        events.append("session-published")
        original_publish(owned, fingerprint)

    def fail_after_readiness(_session: str) -> None:
        events.append("ready")
        raise RuntimeError("private readiness failure")

    monkeypatch.setattr(loop, "add_signal_handler", add_signal_handler)
    monkeypatch.setattr(loop, "remove_signal_handler", remove_signal_handler)
    monkeypatch.setattr(control.OwnedSession, "publish", publish)

    with pytest.raises(control.RuntimeOwnerStartupError):
        await run_local_runtime(
            _simulation_config(),
            "signal-readiness",
            state_directory=short_state_directory,
            history_directory=history_root,
            ready=fail_after_readiness,
        )

    assert events == [
        "signal-installed",
        "session-published",
        "ready",
        "signal-restored",
    ]
    record = list_runs(root=history_root)[0]
    assert record.result is RunResult.STARTUP_FAILED
    assert record.stop_reason is StopReason.STARTUP_FAILURE
    assert not (short_state_directory / "signal-readiness").exists()


@pytest.mark.asyncio
async def test_post_ready_owner_failure_finalizes_runtime_failed(
    short_state_directory: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    history_root = (
        short_state_directory.parent
        / f"{short_state_directory.name}-history-post-ready-failure"
    )
    published: list[str] = []

    class FailingWait:
        async def wait(self) -> None:
            raise ControlProtocolError

        def set(self) -> None:
            pass

    class PostReadyCoordinator(StopCoordinator):
        def __init__(self) -> None:
            super().__init__()
            self.requested = cast(asyncio.Event, FailingWait())

    monkeypatch.setattr(control, "StopCoordinator", PostReadyCoordinator)
    with pytest.raises(ControlProtocolError):
        await run_local_runtime(
            _simulation_config(),
            "post-ready-failure",
            state_directory=short_state_directory,
            history_directory=history_root,
            ready=published.append,
        )

    assert published == ["post-ready-failure"]
    record = list_runs(root=history_root)[0]
    assert record.result is RunResult.RUNTIME_FAILED
    assert record.stop_reason is StopReason.RUNTIME_FAILURE
    assert tuple(
        event.sequence for event in list_events(record.run_id, root=history_root)
    ) == tuple(range(12))
    assert not (short_state_directory / "post-ready-failure").exists()


@pytest.mark.asyncio
async def test_post_ready_failure_precedes_secondary_event_persistence_failure(
    short_state_directory: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    history_root = (
        short_state_directory.parent
        / f"{short_state_directory.name}-history-post-ready-event-failure"
    )
    original_persist = control.HistoryStore.persist_events
    persist_calls = 0

    class FailingWait:
        async def wait(self) -> None:
            raise ControlProtocolError

        def set(self) -> None:
            pass

    class PostReadyCoordinator(StopCoordinator):
        def __init__(self) -> None:
            super().__init__()
            self.requested = cast(asyncio.Event, FailingWait())

    def fail_second_persist(
        store: control.HistoryStore,
        *args: object,
        **kwargs: object,
    ) -> int | None:
        nonlocal persist_calls
        persist_calls += 1
        if persist_calls == 2:
            raise HistoryStoreError("private sqlite detail")
        return original_persist(store, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(control, "StopCoordinator", PostReadyCoordinator)
    monkeypatch.setattr(control.HistoryStore, "persist_events", fail_second_persist)
    with pytest.raises(ControlProtocolError):
        await run_local_runtime(
            _simulation_config(),
            "post-event",
            state_directory=short_state_directory,
            history_directory=history_root,
        )

    assert persist_calls == 2
    record = list_runs(root=history_root)[0]
    assert record.result is RunResult.RUNTIME_FAILED
    assert record.stop_reason is StopReason.RUNTIME_FAILURE
    assert record.event_high_water_mark == 3
    assert tuple(
        event.sequence for event in list_events(record.run_id, root=history_root)
    ) == (0, 1, 2, 3)
    assert not (short_state_directory / "post-event").exists()


@pytest.mark.asyncio
async def test_task_cancellation_closes_history_store_and_releases_session(
    short_state_directory: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    history_root = short_state_directory.parent / f"{short_state_directory.name}-history-cancel"
    ready = asyncio.Event()
    close_calls = 0
    original_close = control.HistoryStore.close

    def count_close(store: control.HistoryStore) -> None:
        nonlocal close_calls
        close_calls += 1
        original_close(store)

    monkeypatch.setattr(control.HistoryStore, "close", count_close)
    task = asyncio.create_task(
        run_local_runtime(
            _simulation_config(),
            "cancelled",
            state_directory=short_state_directory,
            history_directory=history_root,
            ready=lambda _session: ready.set(),
        )
    )
    await asyncio.wait_for(ready.wait(), timeout=5)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert close_calls == 1
    assert not (short_state_directory / "cancelled").exists()
    reopened = control.open_writer(root=history_root)
    reopened.close()


@pytest.mark.asyncio
async def test_unexpected_base_exception_closes_history_store(
    short_state_directory: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    history_root = short_state_directory.parent / f"{short_state_directory.name}-history-base"
    close_calls = 0
    original_close = control.HistoryStore.close

    class OwnerAbort(BaseException):
        pass

    class FailingWait:
        async def wait(self) -> None:
            raise OwnerAbort

        def set(self) -> None:
            pass

    class BaseExceptionCoordinator(StopCoordinator):
        def __init__(self) -> None:
            super().__init__()
            self.requested = cast(asyncio.Event, FailingWait())

    def count_close(store: control.HistoryStore) -> None:
        nonlocal close_calls
        close_calls += 1
        original_close(store)

    monkeypatch.setattr(control, "StopCoordinator", BaseExceptionCoordinator)
    monkeypatch.setattr(control.HistoryStore, "close", count_close)
    with pytest.raises(OwnerAbort):
        await run_local_runtime(
            _simulation_config(),
            "base-exception",
            state_directory=short_state_directory,
            history_directory=history_root,
        )

    assert close_calls == 1
    assert not (short_state_directory / "base-exception").exists()
    reopened = control.open_writer(root=history_root)
    reopened.close()


@pytest.mark.asyncio
async def test_cleanup_failure_finalizes_cleanup_failed(
    short_state_directory: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    history_root = (
        short_state_directory.parent
        / f"{short_state_directory.name}-history-cleanup-failure"
    )
    finalize_calls = 0
    original_finalize = control.HistoryStore.finalize_run

    class LocalStopServer:
        def __init__(
            self,
            _layout: object,
            _operations: object,
            coordinator: StopCoordinator,
        ) -> None:
            self._coordinator = coordinator

        async def start(self) -> None:
            self._coordinator.request_local_stop()

        def stop_accepting(self) -> None:
            pass

        async def wait_handlers(self) -> None:
            pass

        async def close(self) -> None:
            pass

    async def failed_cleanup(
        _operations: RuntimeOperations,
        *,
        persist_events: Callable[[], None] | None = None,
    ) -> bool:
        if persist_events is not None:
            persist_events()
        return False

    def count_finalize(
        store: control.HistoryStore,
        *args: object,
        **kwargs: object,
    ) -> object:
        nonlocal finalize_calls
        finalize_calls += 1
        return original_finalize(store, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(control, "LocalControlServer", LocalStopServer)
    monkeypatch.setattr(control, "_cleanup_operations", failed_cleanup)
    monkeypatch.setattr(control.HistoryStore, "finalize_run", count_finalize)
    with pytest.raises(control.RuntimeOwnerCleanupError):
        await run_local_runtime(
            _simulation_config(),
            "cleanup-failure",
            state_directory=short_state_directory,
            history_directory=history_root,
        )

    record = list_runs(root=history_root)[0]
    assert record.result is RunResult.CLEANUP_FAILED
    assert record.stop_reason is StopReason.CLEANUP_FAILURE
    assert finalize_calls == 1
    assert not (short_state_directory / "cleanup-failure").exists()


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ("safe_stop", "shutdown"))
async def test_runtime_cleanup_step_failure_finalizes_cleanup_failed(
    failure: str,
    short_state_directory: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    history_root = (
        short_state_directory.parent
        / f"{short_state_directory.name}-history-{failure}"
    )

    class FailingCleanupOperations:
        def __init__(self, *_args: object) -> None:
            self.manager_state = RuntimeManagerState.STOPPED

        async def start(self) -> None:
            self.manager_state = RuntimeManagerState.RUNNING

        def snapshot(self) -> RuntimeOperationsSnapshot:
            return cast(
                RuntimeOperationsSnapshot,
                type(
                    "Snapshot",
                    (),
                    {"manager_state": self.manager_state, "event_high_water_mark": 3},
                )(),
            )

        async def safe_stop(self) -> None:
            if failure == "safe_stop":
                raise RuntimeError("private safe-stop detail")

        async def shutdown(self) -> None:
            if failure == "shutdown":
                raise RuntimeError("private shutdown detail")
            self.manager_state = RuntimeManagerState.STOPPED

    class LocalStopServer:
        def __init__(
            self,
            _layout: object,
            _operations: object,
            coordinator: StopCoordinator,
        ) -> None:
            self._coordinator = coordinator

        async def start(self) -> None:
            self._coordinator.request_local_stop()

        def stop_accepting(self) -> None:
            pass

        async def wait_handlers(self) -> None:
            pass

        async def close(self) -> None:
            pass

    monkeypatch.setattr(control, "RuntimeOperations", FailingCleanupOperations)
    monkeypatch.setattr(control, "LocalControlServer", LocalStopServer)
    with pytest.raises(control.RuntimeOwnerCleanupError):
        await run_local_runtime(
            _simulation_config(),
            f"{failure}-failure",
            state_directory=short_state_directory,
            history_directory=history_root,
        )

    record = list_runs(root=history_root)[0]
    assert record.result is RunResult.CLEANUP_FAILED
    assert record.stop_reason is StopReason.CLEANUP_FAILURE


@pytest.mark.asyncio
async def test_session_cleanup_failure_is_retryable_and_finalizes_cleanup_failed(
    short_state_directory: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    history_root = (
        short_state_directory.parent
        / f"{short_state_directory.name}-history-session-cleanup"
    )
    cleanup_calls: list[bool] = []
    original_cleanup = control.OwnedSession.cleanup

    class LocalStopServer:
        def __init__(
            self,
            _layout: object,
            _operations: object,
            coordinator: StopCoordinator,
        ) -> None:
            self._coordinator = coordinator

        async def start(self) -> None:
            self._coordinator.request_local_stop()

        def stop_accepting(self) -> None:
            pass

        async def wait_handlers(self) -> None:
            pass

        async def close(self) -> None:
            pass

    def fail_once(owned: control.OwnedSession, *, final: bool = False) -> bool:
        cleanup_calls.append(final)
        if not final:
            return False
        return original_cleanup(owned, final=True)

    monkeypatch.setattr(control, "LocalControlServer", LocalStopServer)
    monkeypatch.setattr(control.OwnedSession, "cleanup", fail_once)
    with pytest.raises(control.RuntimeOwnerCleanupError):
        await run_local_runtime(
            _simulation_config(),
            "session-cleanup",
            state_directory=short_state_directory,
            history_directory=history_root,
        )

    assert cleanup_calls == [False, True]
    assert not (short_state_directory / "session-cleanup").exists()
    record = list_runs(root=history_root)[0]
    assert record.result is RunResult.CLEANUP_FAILED
    assert record.stop_reason is StopReason.CLEANUP_FAILURE


@pytest.mark.asyncio
async def test_history_only_finalization_failure_does_not_skip_cleanup(
    short_state_directory: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    history_root = (
        short_state_directory.parent
        / f"{short_state_directory.name}-history-finalize-failure"
    )
    original_cleanup = control._cleanup_operations  # pyright: ignore[reportPrivateUsage]
    cleanup_calls = 0
    finalize_calls = 0

    class LocalStopServer:
        def __init__(
            self,
            _layout: object,
            _operations: object,
            coordinator: StopCoordinator,
        ) -> None:
            self._coordinator = coordinator

        async def start(self) -> None:
            self._coordinator.request_local_stop()

        def stop_accepting(self) -> None:
            pass

        async def wait_handlers(self) -> None:
            pass

        async def close(self) -> None:
            pass

    async def successful_cleanup(
        operations: RuntimeOperations,
        *,
        persist_events: Callable[[], None] | None = None,
    ) -> bool:
        nonlocal cleanup_calls
        cleanup_calls += 1
        return await original_cleanup(operations, persist_events=persist_events)

    def fail_finalize(*_args: object, **_kwargs: object) -> None:
        nonlocal finalize_calls
        finalize_calls += 1
        raise HistoryStoreError("private sqlite detail")

    monkeypatch.setattr(control, "LocalControlServer", LocalStopServer)
    monkeypatch.setattr(control, "_cleanup_operations", successful_cleanup)
    monkeypatch.setattr(control.HistoryStore, "finalize_run", fail_finalize)
    with pytest.raises(control.RuntimeHistoryError):
        await run_local_runtime(
            _simulation_config(),
            "history-failure",
            state_directory=short_state_directory,
            history_directory=history_root,
        )

    assert cleanup_calls == 1
    assert finalize_calls == 1
    assert not (short_state_directory / "history-failure").exists()
    record = list_runs(root=history_root)[0]
    assert record.result is None
    assert record.ended_at is None


@pytest.mark.asyncio
async def test_finalization_clock_failure_leaves_run_incomplete_after_cleanup(
    short_state_directory: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    history_root = (
        short_state_directory.parent
        / f"{short_state_directory.name}-history-finalize-clock"
    )
    original_open_writer = control.open_writer
    original_cleanup = control._cleanup_operations  # pyright: ignore[reportPrivateUsage]
    original_finalize = control.HistoryStore.finalize_run
    clock_calls = 0
    cleanup_calls = 0
    finalize_calls = 0

    class LocalStopServer:
        def __init__(
            self,
            _layout: object,
            _operations: object,
            coordinator: StopCoordinator,
        ) -> None:
            self._coordinator = coordinator

        async def start(self) -> None:
            self._coordinator.stop_reason = StopReason.CLI_STOP
            self._coordinator.requested.set()

        def stop_accepting(self) -> None:
            pass

        async def wait_handlers(self) -> None:
            pass

        async def close(self) -> None:
            pass

    def fail_finalization_clock() -> datetime:
        nonlocal clock_calls
        clock_calls += 1
        if clock_calls == 14:
            raise RuntimeError("private finalization clock failed")
        return datetime(2026, 10, 18, 10, 11, 12, 123456, tzinfo=UTC)

    def open_with_clock(*, root: Path | None = None) -> control.HistoryStore:
        return original_open_writer(
            root=root,
            clock=fail_finalization_clock,
        )

    async def count_cleanup(
        operations: RuntimeOperations,
        *,
        persist_events: Callable[[], None] | None = None,
    ) -> bool:
        nonlocal cleanup_calls
        cleanup_calls += 1
        return await original_cleanup(operations, persist_events=persist_events)

    def count_finalize(
        store: control.HistoryStore,
        *args: object,
        **kwargs: object,
    ) -> object:
        nonlocal finalize_calls
        finalize_calls += 1
        return original_finalize(store, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(control, "open_writer", open_with_clock)
    monkeypatch.setattr(control, "LocalControlServer", LocalStopServer)
    monkeypatch.setattr(control, "_cleanup_operations", count_cleanup)
    monkeypatch.setattr(control.HistoryStore, "finalize_run", count_finalize)
    with pytest.raises(control.RuntimeHistoryError) as caught:
        await run_local_runtime(
            _simulation_config(),
            "final-clock",
            state_directory=short_state_directory,
            history_directory=history_root,
        )

    assert str(caught.value) == ""
    assert cleanup_calls == 1
    assert finalize_calls == 1
    assert not (short_state_directory / "final-clock").exists()
    record = list_runs(root=history_root)[0]
    assert record.ended_at is None
    assert record.result is None
    assert record.stop_reason is None
    assert record.event_high_water_mark == 11
    assert tuple(
        event.sequence for event in list_events(record.run_id, root=history_root)
    ) == tuple(range(12))
    reopened = control.open_writer(root=history_root)
    reopened.close()


@pytest.mark.asyncio
async def test_bounded_sqlite_contention_does_not_skip_runtime_cleanup(
    short_state_directory: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    history_root = (
        short_state_directory.parent / f"{short_state_directory.name}-history-contention"
    )
    lock_connection: sqlite3.Connection | None = None
    contention_active = False
    cleanup_calls = 0
    contended_persist_events_attempts = 0
    contended_finalize_run_attempts = 0
    original_cleanup = control._cleanup_operations  # pyright: ignore[reportPrivateUsage]
    original_persist_events = control.HistoryStore.persist_events
    original_finalize_run = control.HistoryStore.finalize_run
    expected_contended_history_write_attempts = 2
    hosted_scheduler_filesystem_margin_seconds = 2.0
    minimum_contention_elapsed_seconds = 0.5
    production_write_timeout_seconds = (
        history._WRITE_TIMEOUT_SECONDS  # pyright: ignore[reportPrivateUsage]
    )
    aggregate_upper_bound_seconds = (
        expected_contended_history_write_attempts * production_write_timeout_seconds
        + hosted_scheduler_filesystem_margin_seconds
    )

    class LockingStopServer:
        def __init__(
            self,
            _layout: object,
            _operations: object,
            coordinator: StopCoordinator,
        ) -> None:
            self._coordinator = coordinator

        async def start(self) -> None:
            nonlocal contention_active, lock_connection
            lock_connection = sqlite3.connect(
                history_root / "history.sqlite3",
                timeout=0,
                isolation_level=None,
            )
            lock_connection.execute("BEGIN IMMEDIATE")
            contention_active = True
            self._coordinator.stop_reason = StopReason.CLI_STOP
            self._coordinator.requested.set()

        def stop_accepting(self) -> None:
            pass

        async def wait_handlers(self) -> None:
            pass

        async def close(self) -> None:
            pass

    async def count_cleanup(
        operations: RuntimeOperations,
        *,
        persist_events: Callable[[], None] | None = None,
    ) -> bool:
        nonlocal cleanup_calls
        cleanup_calls += 1
        return await original_cleanup(operations, persist_events=persist_events)

    def count_contended_persist_events(
        store: control.HistoryStore,
        *args: object,
        **kwargs: object,
    ) -> object:
        nonlocal contended_persist_events_attempts
        if contention_active:
            contended_persist_events_attempts += 1
        return original_persist_events(store, *args, **kwargs)  # type: ignore[arg-type]

    def count_contended_finalize_run(
        store: control.HistoryStore,
        *args: object,
        **kwargs: object,
    ) -> object:
        nonlocal contended_finalize_run_attempts
        if contention_active:
            contended_finalize_run_attempts += 1
        return original_finalize_run(store, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(control, "LocalControlServer", LockingStopServer)
    monkeypatch.setattr(control, "_cleanup_operations", count_cleanup)
    monkeypatch.setattr(
        control.HistoryStore,
        "persist_events",
        count_contended_persist_events,
    )
    monkeypatch.setattr(
        control.HistoryStore,
        "finalize_run",
        count_contended_finalize_run,
    )
    started = time.monotonic()
    try:
        with pytest.raises(control.RuntimeHistoryError):
            await run_local_runtime(
                _simulation_config(),
                "history-contention",
                state_directory=short_state_directory,
                history_directory=history_root,
            )
    finally:
        if lock_connection is not None:
            lock_connection.rollback()
            lock_connection.close()
        elapsed = time.monotonic() - started
        contention_active = False

    # Two independent 1 s busy timeouts plus an explicit hosted scheduling and
    # filesystem margin form a regression-harness budget, not a latency promise.
    # The lower bound rejects an immediate-return regression; counters prove both waits.
    assert cleanup_calls == 1
    assert contended_persist_events_attempts == 1
    assert contended_finalize_run_attempts == 1
    assert (
        contended_persist_events_attempts + contended_finalize_run_attempts
        == expected_contended_history_write_attempts
    )
    assert not (short_state_directory / "history-contention").exists()
    records = list_runs(root=history_root)
    assert len(records) == 1
    record = records[0]
    assert (record.ended_at, record.result, record.stop_reason) == (None, None, None)
    assert record.result is None
    assert record.ended_at is None
    assert minimum_contention_elapsed_seconds <= elapsed < aggregate_upper_bound_seconds


@pytest.mark.asyncio
async def test_cleanup_and_history_failure_attempts_finalization_once(
    short_state_directory: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    history_root = (
        short_state_directory.parent
        / f"{short_state_directory.name}-history-combined-failure"
    )
    finalize_calls = 0
    cleanup_calls = 0

    class LocalStopServer:
        def __init__(
            self,
            _layout: object,
            _operations: object,
            coordinator: StopCoordinator,
        ) -> None:
            self._coordinator = coordinator

        async def start(self) -> None:
            self._coordinator.request_local_stop()

        def stop_accepting(self) -> None:
            pass

        async def wait_handlers(self) -> None:
            pass

        async def close(self) -> None:
            pass

    async def failed_cleanup(
        _operations: RuntimeOperations,
        *,
        persist_events: Callable[[], None] | None = None,
    ) -> bool:
        nonlocal cleanup_calls
        cleanup_calls += 1
        if persist_events is not None:
            persist_events()
        return False

    def fail_finalize(*_args: object, **_kwargs: object) -> None:
        nonlocal finalize_calls
        finalize_calls += 1
        raise HistoryStoreError("private sqlite detail")

    monkeypatch.setattr(control, "LocalControlServer", LocalStopServer)
    monkeypatch.setattr(control, "_cleanup_operations", failed_cleanup)
    monkeypatch.setattr(control.HistoryStore, "finalize_run", fail_finalize)
    with pytest.raises(control.RuntimeOwnerCleanupError):
        await run_local_runtime(
            _simulation_config(),
            "combined-failure",
            state_directory=short_state_directory,
            history_directory=history_root,
        )

    assert cleanup_calls == 1
    assert finalize_calls == 1
    assert not (short_state_directory / "combined-failure").exists()
    record = list_runs(root=history_root)[0]
    assert record.result is None
    assert record.ended_at is None


def test_missing_session_is_stable(tmp_path: Path) -> None:
    with pytest.raises(SessionNotRunningError):
        asyncio.run(control.request_status("alpha", state_directory=tmp_path / "missing"))


def _simulation_config() -> RuntimeConfig:
    return _config_for_model("motor.simulated")


def _config_for_model(model: str) -> RuntimeConfig:
    return RuntimeConfig(
        schema_version="1",
        resources=[
            ResourceDefinition(
                identity=ResourceIdentity("sim_motor"),
                model=model,
                settings={},
            )
        ],
    )


def _status() -> StatusReply:
    identity = ResourceIdentity("sim_motor")
    return StatusReply(
        session="alpha",
        manager_state=RuntimeManagerState.RUNNING,
        resources=(
            ResourceStatus(
                identity,
                LifecycleState.RUNNING,
                HealthStatus.HEALTHY,
                None,
            ),
        ),
        successful_start_order=(identity,),
        active_resource_order=(identity,),
        event_high_water_mark=3,
        latest_event_summary="runtime running",
    )


def _preview_reply() -> PreviewReply:
    return PreviewReply(
        session="alpha",
        preview=SimulationPreviewSnapshot(
            schema_version="1",
            runtime_state=RuntimeManagerState.RUNNING,
            resources=(_preview_resource("sim_motor"),),
        ),
    )


def _preview_resource(identity: str) -> SimulationPreviewResourceSnapshot:
    return SimulationPreviewResourceSnapshot(
        identity=ResourceIdentity(identity),
        kind="motor",
        lifecycle_state=LifecycleState.RUNNING,
        health_status=HealthStatus.HEALTHY,
        health_summary=None,
        state=SimulationMotorPreviewState(0.0, 0.0, 0.0, 0),
    )


def _artifact_snapshot(directory: Path) -> dict[str, tuple[int, int, int, int]]:
    return {
        entry.name: (
            entry.lstat().st_ino,
            entry.lstat().st_mode,
            entry.lstat().st_size,
            entry.lstat().st_mtime_ns,
        )
        for entry in directory.iterdir()
    }


@pytest.fixture
def short_state_directory() -> Iterator[Path]:
    with tempfile.TemporaryDirectory(prefix="hiyelx-rto2-") as path:
        state = Path(path)
        try:
            yield state
        finally:
            for history_root in state.parent.glob(f"{state.name}-history*"):
                shutil.rmtree(history_root)
