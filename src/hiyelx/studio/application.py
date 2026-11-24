"""Sanitized Studio reads over existing typed runtime boundaries."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from hiyelx import __version__
from hiyelx.components.mock import register_mock_components
from hiyelx.core.registry import ComponentRegistry
from hiyelx.runtime.control import (
    InvalidSessionIdError,
    RuntimeControlError,
    RuntimePreviewUnavailableError,
    RuntimePreviewUnsupportedError,
    SessionNotRunningError,
    list_observable_sessions,
    request_preview,
    validate_session_id,
)
from hiyelx.simulation import SimulationPreviewSnapshot

STUDIO_RUNTIME_INFO_SCHEMA_VERSION = "1"
SUPPORTED_CONFIG_SCHEMA_VERSIONS: tuple[str, ...] = ("1", "2")


@dataclass(frozen=True, slots=True)
class RuntimeModelSummary:
    """One sanitized built-in component model entry exposed to Studio."""

    model: str
    category: str
    capabilities: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class StudioRuntimeInfo:
    """Sanitized read-only summary of installed Runtime package and models."""

    schema_version: str
    package_version: str
    supported_config_schemas: tuple[str, ...]
    registered_models: tuple[RuntimeModelSummary, ...]


class StudioErrorCode(StrEnum):
    """Stable sanitized failure categories for the future HTTP adapter."""

    INVALID_REQUEST = "invalid_request"
    SESSIONS_UNAVAILABLE = "sessions_unavailable"
    SESSION_NOT_RUNNING = "session_not_running"
    PREVIEW_UNAVAILABLE = "preview_unavailable"
    PREVIEW_UNSUPPORTED = "preview_unsupported"
    APPLICATION_ERROR = "application_error"


_STUDIO_ERROR_MESSAGES = {
    StudioErrorCode.INVALID_REQUEST: "Studio request is invalid.",
    StudioErrorCode.SESSIONS_UNAVAILABLE: "Studio could not list local sessions.",
    StudioErrorCode.SESSION_NOT_RUNNING: "The selected session is not running.",
    StudioErrorCode.PREVIEW_UNAVAILABLE: "Studio preview is temporarily unavailable.",
    StudioErrorCode.PREVIEW_UNSUPPORTED: (
        "This Studio version cannot read this preview schema."
    ),
    StudioErrorCode.APPLICATION_ERROR: "Studio could not read this snapshot.",
}


class StudioApplicationError(Exception):
    """One typed Studio failure containing no private runtime detail."""

    def __init__(self, code: StudioErrorCode) -> None:
        self.code = code
        super().__init__(_STUDIO_ERROR_MESSAGES[code])


async def list_sessions(
    *,
    state_directory: Path | None = None,
) -> tuple[str, ...]:
    """List observable local sessions through the read-only discovery boundary."""
    failed = False
    try:
        return await asyncio.to_thread(
            list_observable_sessions,
            state_directory=state_directory,
        )
    except (RuntimeControlError, OSError):
        failed = True
    if failed:
        raise StudioApplicationError(StudioErrorCode.SESSIONS_UNAVAILABLE)
    raise AssertionError("unreachable")


async def get_preview(
    session: str,
    *,
    state_directory: Path | None = None,
) -> SimulationPreviewSnapshot:
    """Return one typed schema-v1 preview or one sanitized Studio failure."""
    failure: StudioErrorCode | None = None
    try:
        validated_session = validate_session_id(session)
        reply = await request_preview(
            validated_session,
            state_directory=state_directory,
        )
    except InvalidSessionIdError:
        failure = StudioErrorCode.INVALID_REQUEST
    except SessionNotRunningError:
        failure = StudioErrorCode.SESSION_NOT_RUNNING
    except RuntimePreviewUnavailableError:
        failure = StudioErrorCode.PREVIEW_UNAVAILABLE
    except RuntimePreviewUnsupportedError:
        failure = StudioErrorCode.PREVIEW_UNSUPPORTED
    except (RuntimeControlError, OSError):
        failure = StudioErrorCode.APPLICATION_ERROR
    else:
        return reply.preview

    raise StudioApplicationError(failure)


async def get_runtime_info() -> StudioRuntimeInfo:
    """Return a sanitized read-only summary of installed Runtime capabilities."""
    registry = ComponentRegistry()
    register_mock_components(registry)
    models = tuple(
        RuntimeModelSummary(
            model=model_name,
            category=str(entry.category),
            capabilities=tuple(sorted(str(cap) for cap in entry.capabilities)),
        )
        for model_name in registry.registered_models()
        for entry in (registry.resolve(model_name),)
    )
    return StudioRuntimeInfo(
        schema_version=STUDIO_RUNTIME_INFO_SCHEMA_VERSION,
        package_version=__version__,
        supported_config_schemas=SUPPORTED_CONFIG_SCHEMA_VERSIONS,
        registered_models=models,
    )
