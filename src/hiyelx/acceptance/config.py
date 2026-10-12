"""Strict hardware-acceptance configuration loading with no device I/O."""

from __future__ import annotations

import json
import re
from math import isfinite
from pathlib import Path
from typing import Literal, Self, cast

import yaml
from pydantic import BaseModel, ConfigDict, ValidationError, field_validator, model_validator

from hiyelx.acceptance.errors import AcceptanceConfigurationError

PHYSICAL_OPERATION_CONSENT = "I_ACCEPT_PHYSICAL_OPERATION"
_SAFE_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


class AcceptanceCommandBounds(BaseModel):
    """Finite velocity-command interval that must strictly contain zero."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    minimum_rad_s: float
    maximum_rad_s: float

    @model_validator(mode="after")
    def _bounds_must_be_finite_ordered_and_contain_stop(self) -> Self:
        minimum = self.minimum_rad_s
        maximum = self.maximum_rad_s
        if not isfinite(minimum) or not isfinite(maximum):
            raise ValueError("command bounds must be finite")
        if minimum >= maximum:
            raise ValueError("command bounds must be ordered")
        if minimum >= 0.0 or maximum <= 0.0:
            raise ValueError("command bounds must strictly contain zero")
        return self


class HardwareAcceptanceConfig(BaseModel):
    """Immutable inputs for one bounded motor-acceptance session."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    schema_version: Literal["1"]
    driver_identity: str
    expected_motor_model: str
    transport_identifier: str
    device_id: int
    baud_rate: int
    command_bounds: AcceptanceCommandBounds
    operation_deadline_seconds: float
    movement_authorized: bool
    evidence_session_id: str

    @field_validator("driver_identity", "expected_motor_model", "evidence_session_id")
    @classmethod
    def _identifier_must_be_safe(cls, value: str) -> str:
        if _SAFE_IDENTIFIER.fullmatch(value) is None:
            raise ValueError("identifier has an invalid format")
        return value

    @field_validator("transport_identifier")
    @classmethod
    def _transport_must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("transport_identifier must not be blank")
        return value

    @field_validator("device_id")
    @classmethod
    def _device_id_must_be_non_negative(cls, value: int) -> int:
        if value < 0:
            raise ValueError("device_id must not be negative")
        return value

    @field_validator("baud_rate")
    @classmethod
    def _baud_rate_must_be_positive(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("baud_rate must be positive")
        return value

    @field_validator("operation_deadline_seconds")
    @classmethod
    def _deadline_must_be_positive_and_finite(cls, value: float) -> float:
        if not isfinite(value) or value <= 0.0:
            raise ValueError("operation_deadline_seconds must be positive and finite")
        return value


def load_hardware_acceptance_config(path: str | Path) -> HardwareAcceptanceConfig:
    """Load one local YAML/JSON document without revealing its path in errors."""
    config_path = Path(path)
    suffix = config_path.suffix.lower()
    if suffix not in {".yaml", ".yml", ".json"}:
        raise AcceptanceConfigurationError("unsupported acceptance configuration format")
    try:
        source = config_path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        raise AcceptanceConfigurationError(
            "acceptance configuration could not be read"
        ) from None
    try:
        if suffix == ".json":
            document = cast(object, json.loads(source))
        else:
            document = cast(object, yaml.safe_load(source))
    except (json.JSONDecodeError, yaml.YAMLError):
        raise AcceptanceConfigurationError(
            "acceptance configuration could not be parsed"
        ) from None
    if not isinstance(document, dict):
        raise AcceptanceConfigurationError("acceptance configuration root must be an object")
    try:
        return HardwareAcceptanceConfig.model_validate(document, strict=True)
    except ValidationError:
        raise AcceptanceConfigurationError(
            "acceptance configuration validation failed"
        ) from None
