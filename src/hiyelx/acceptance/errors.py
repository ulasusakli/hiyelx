"""Sanitized errors for the internal hardware-acceptance boundary."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from hiyelx.acceptance.harness import AcceptanceEvidence


class HardwareAcceptanceError(Exception):
    """Base class for bounded hardware-acceptance failures."""


class AcceptanceConfigurationError(HardwareAcceptanceError):
    """Raised when an acceptance document cannot be loaded or validated."""


class PhysicalConsentRequiredError(HardwareAcceptanceError):
    """Raised when movement is requested without the exact consent value."""

    def __init__(self) -> None:
        super().__init__("explicit physical-operation consent is required")


class HardwareSelectionRequiredError(HardwareAcceptanceError):
    """Raised when physical execution was not selected explicitly by pytest."""

    def __init__(self) -> None:
        super().__init__("explicit pytest hardware selection is required")


class MovementNotAuthorizedError(HardwareAcceptanceError):
    """Raised when an execution request uses a preflight-only configuration."""

    def __init__(self) -> None:
        super().__init__("physical movement is not authorized by the configuration")


class AcceptanceDriverUnavailableError(HardwareAcceptanceError):
    """Raised when the requested registered driver cannot be resolved."""

    def __init__(self) -> None:
        super().__init__("requested acceptance driver is unavailable")


class AcceptanceModelMismatchError(HardwareAcceptanceError):
    """Raised when a declared or identified motor model is incompatible."""

    def __init__(self) -> None:
        super().__init__("expected motor model is incompatible with the acceptance driver")


class AcceptanceConstraintError(HardwareAcceptanceError):
    """Raised when driver-specific acceptance limits are not satisfied."""

    def __init__(self) -> None:
        super().__init__("acceptance configuration exceeds the driver profile")


class AcceptanceCommandOutOfBoundsError(HardwareAcceptanceError):
    """Raised before construction when a command exceeds configured bounds."""

    def __init__(self) -> None:
        super().__init__("acceptance command is outside the configured bounds")


class AcceptanceExecutionError(HardwareAcceptanceError):
    """Sanitized failure with deterministic evidence and no backend text."""

    def __init__(self, stage: str, evidence: AcceptanceEvidence) -> None:
        self.stage = stage
        self.evidence = evidence
        super().__init__(f"hardware acceptance failed during {stage}")
