"""Sanitized Studio reads over existing typed runtime boundaries."""

from __future__ import annotations

import asyncio
from enum import StrEnum
from pathlib import Path

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
