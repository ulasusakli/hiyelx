import asyncio
import json
import os
import socket
import stat
import tempfile
from collections.abc import Iterator
from pathlib import Path
from typing import cast

import pytest

from hiyelx.config import ResourceDefinition, RuntimeConfig
from hiyelx.resources import HealthStatus, LifecycleState, ResourceIdentity
from hiyelx.runtime import (
    RuntimeEvent,
    RuntimeEventOperation,
    RuntimeEventOutcome,
    RuntimeManagerState,
    RuntimeOperationsSnapshot,
    RuntimeResourceSnapshot,
    control,
)
from hiyelx.runtime.control import (
    MAX_MESSAGE_BYTES,
    PROTOCOL_VERSION,
    STATE_DIRECTORY_ENV,
    ControlCommand,
    ControlErrorCode,
    ControlProtocolError,
    ControlRequest,
    FailureReply,
    InvalidSessionIdError,
    ResourceStatus,
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
    reserve_session,
    resolve_state_directory,
    run_local_runtime,
    status_reply,
    validate_session_id,
    validate_simulation_config,
)
from hiyelx.runtime.operations import RuntimeOperations


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
    with pytest.raises(UnsupportedRuntimeModelError):
        await run_local_runtime(
            _config_for_model("motor.dynamixel.xl430_w250_t"),
            "hardware",
            state_directory=short_state_directory,
        )
    assert not constructed
    entries = await asyncio.to_thread(lambda: tuple(short_state_directory.iterdir()))
    assert entries == ()


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
    with tempfile.TemporaryDirectory(prefix="hiyelx-rto2-", dir="/private/tmp") as path:
        yield Path(path)
