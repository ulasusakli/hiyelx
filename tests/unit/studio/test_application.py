import json
from pathlib import Path

import pytest

from hiyelx.resources import HealthStatus, LifecycleState, ResourceIdentity
from hiyelx.runtime.control import (
    ControlProtocolError,
    PreviewReply,
    RuntimePreviewUnavailableError,
    RuntimePreviewUnsupportedError,
    SessionNotRunningError,
    UnsafeSessionPathError,
)
from hiyelx.runtime.state import RuntimeManagerState
from hiyelx.simulation import (
    SimulationMotorPreviewState,
    SimulationPreviewResourceSnapshot,
    SimulationPreviewSnapshot,
    render_simulation_preview_json,
)
from hiyelx.studio import application
from hiyelx.studio.application import (
    RuntimeModelSummary,
    StudioApplicationError,
    StudioErrorCode,
    StudioRuntimeInfo,
    get_preview,
    get_runtime_info,
    list_sessions,
)


@pytest.mark.asyncio
async def test_list_sessions_returns_exact_discovery_projection(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    calls: list[Path | None] = []

    def discover(*, state_directory: Path | None = None) -> tuple[str, ...]:
        calls.append(state_directory)
        return ("alpha", "zeta")

    monkeypatch.setattr(application, "list_observable_sessions", discover)

    assert await list_sessions(state_directory=tmp_path) == ("alpha", "zeta")
    assert calls == [tmp_path]


@pytest.mark.asyncio
async def test_list_sessions_maps_private_discovery_failure_to_sanitized_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail(*, state_directory: Path | None = None) -> tuple[str, ...]:
        del state_directory
        raise UnsafeSessionPathError("/tmp/private pid=42 manifest.json")

    monkeypatch.setattr(application, "list_observable_sessions", fail)

    with pytest.raises(StudioApplicationError) as caught:
        await list_sessions()

    _assert_sanitized(
        caught.value,
        StudioErrorCode.SESSIONS_UNAVAILABLE,
        "Studio could not list local sessions.",
    )


@pytest.mark.asyncio
async def test_get_preview_returns_typed_snapshot_with_canonical_serialization(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    snapshot = _snapshot()
    calls: list[tuple[str, Path | None]] = []

    async def preview(
        session: str,
        *,
        state_directory: Path | None = None,
    ) -> PreviewReply:
        calls.append((session, state_directory))
        return PreviewReply(session, snapshot)

    monkeypatch.setattr(application, "request_preview", preview)

    result = await get_preview("alpha")

    assert result is snapshot
    assert calls == [("alpha", None)]
    assert json.loads(render_simulation_preview_json(result)) == {
        "resources": [
            {
                "health_status": "healthy",
                "health_summary": None,
                "identity": "sim_motor",
                "kind": "motor",
                "lifecycle_state": "running",
                "state": {
                    "angular_position_radians": 1.25,
                    "angular_velocity_radians_per_second": 0.5,
                    "revision": 3,
                    "simulation_time_seconds": 2.5,
                },
            }
        ],
        "runtime_state": "running",
        "schema_version": "1",
    }


@pytest.mark.parametrize(
    ("runtime_error", "code", "message"),
    (
        (
            SessionNotRunningError("private pid=7"),
            StudioErrorCode.SESSION_NOT_RUNNING,
            "The selected session is not running.",
        ),
        (
            RuntimePreviewUnavailableError(),
            StudioErrorCode.PREVIEW_UNAVAILABLE,
            "Studio preview is temporarily unavailable.",
        ),
        (
            RuntimePreviewUnsupportedError(),
            StudioErrorCode.PREVIEW_UNSUPPORTED,
            "This Studio version cannot read this preview schema.",
        ),
        (
            ControlProtocolError("socket=/tmp/private secret=value"),
            StudioErrorCode.APPLICATION_ERROR,
            "Studio could not read this snapshot.",
        ),
    ),
)
@pytest.mark.asyncio
async def test_get_preview_maps_runtime_failures_to_exact_sanitized_categories(
    runtime_error: Exception,
    code: StudioErrorCode,
    message: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fail(
        session: str,
        *,
        state_directory: Path | None = None,
    ) -> PreviewReply:
        del session, state_directory
        raise runtime_error

    monkeypatch.setattr(application, "request_preview", fail)

    with pytest.raises(StudioApplicationError) as caught:
        await get_preview("alpha")

    _assert_sanitized(caught.value, code, message)


@pytest.mark.asyncio
async def test_invalid_session_is_rejected_before_preview_access(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    called = False

    async def preview(
        session: str,
        *,
        state_directory: Path | None = None,
    ) -> PreviewReply:
        del session, state_directory
        nonlocal called
        called = True
        raise AssertionError("unreachable")

    monkeypatch.setattr(application, "request_preview", preview)

    with pytest.raises(StudioApplicationError) as caught:
        await get_preview("../private")

    _assert_sanitized(
        caught.value,
        StudioErrorCode.INVALID_REQUEST,
        "Studio request is invalid.",
    )
    assert not called


def test_application_surface_has_no_runtime_mutation_operation() -> None:
    assert "request_stop" not in application.__dict__
    assert "run_local_runtime" not in application.__dict__
    assert "reserve_session" not in application.__dict__
    assert "hardware" not in application.__dict__


@pytest.mark.asyncio
async def test_get_runtime_info_returns_sorted_sanitized_builtin_models() -> None:
    info = await get_runtime_info()
    assert isinstance(info, StudioRuntimeInfo)
    assert info.schema_version == "1"
    assert info.package_version == "0.2.0a1"
    assert info.supported_config_schemas == ("1", "2")
    model_names = tuple(item.model for item in info.registered_models)
    assert model_names == tuple(sorted(model_names))
    assert "mock.motor" in model_names
    assert "mock.encoder" in model_names
    assert "mock.imu" in model_names
    assert "mock.camera" in model_names
    motor = next(item for item in info.registered_models if item.model == "mock.motor")
    assert motor == RuntimeModelSummary(
        model="mock.motor",
        category="actuator",
        capabilities=("can_set_velocity", "has_angular_position", "has_angular_velocity"),
    )
    rendered = repr(info).lower()
    for private in ("/users/", "/tmp/", "pid", "socket", "secret"):
        assert private not in rendered


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


def _assert_sanitized(
    error: StudioApplicationError,
    code: StudioErrorCode,
    message: str,
) -> None:
    assert error.code is code
    assert str(error) == message
    representation = repr(error)
    assert message in representation
    for private in ("/tmp/", "pid", "manifest", "socket", "secret", "protocol"):
        assert private not in representation.lower()
    assert error.__cause__ is None
    assert error.__context__ is None
