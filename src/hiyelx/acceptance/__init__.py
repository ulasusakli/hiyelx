"""Internal, explicit-opt-in hardware-acceptance readiness boundary."""

from hiyelx.acceptance.config import (
    PHYSICAL_OPERATION_CONSENT,
    AcceptanceCommandBounds,
    HardwareAcceptanceConfig,
    load_hardware_acceptance_config,
)
from hiyelx.acceptance.errors import (
    AcceptanceCommandOutOfBoundsError,
    AcceptanceConfigurationError,
    AcceptanceConstraintError,
    AcceptanceDriverUnavailableError,
    AcceptanceExecutionError,
    AcceptanceModelMismatchError,
    HardwareAcceptanceError,
    HardwareSelectionRequiredError,
    MovementNotAuthorizedError,
    PhysicalConsentRequiredError,
)
from hiyelx.acceptance.harness import (
    AcceptanceEvidence,
    AcceptancePlan,
    AcceptanceSession,
    AcceptanceSessionFactory,
    EvidenceFinalizer,
    TorqueDisableCapable,
    preflight_hardware_acceptance,
    run_physical_acceptance,
    run_physical_acceptance_from_path,
)
from hiyelx.acceptance.profiles import (
    XL430_W250_T_ACCEPTANCE_PROFILE,
    AcceptanceDriverProfile,
)

__all__ = [
    "PHYSICAL_OPERATION_CONSENT",
    "AcceptanceCommandBounds",
    "AcceptanceCommandOutOfBoundsError",
    "AcceptanceConfigurationError",
    "AcceptanceConstraintError",
    "AcceptanceDriverProfile",
    "AcceptanceDriverUnavailableError",
    "AcceptanceEvidence",
    "AcceptanceExecutionError",
    "AcceptanceModelMismatchError",
    "AcceptancePlan",
    "AcceptanceSession",
    "AcceptanceSessionFactory",
    "EvidenceFinalizer",
    "HardwareAcceptanceConfig",
    "HardwareAcceptanceError",
    "HardwareSelectionRequiredError",
    "MovementNotAuthorizedError",
    "PhysicalConsentRequiredError",
    "TorqueDisableCapable",
    "XL430_W250_T_ACCEPTANCE_PROFILE",
    "load_hardware_acceptance_config",
    "preflight_hardware_acceptance",
    "run_physical_acceptance",
    "run_physical_acceptance_from_path",
]
