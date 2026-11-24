"""Typed errors for the HIYELX Component & Driver Manifest Engine."""

from __future__ import annotations

from pathlib import Path


class ManifestError(Exception):
    """Base error for component and driver manifest operations."""


class ManifestLoadError(ManifestError):
    """Raised when a manifest file cannot be read or parsed as YAML."""

    def __init__(self, path: Path, reason: str) -> None:
        self.path = path
        self.reason = reason
        super().__init__(f"{path}: {reason}")


class UnsupportedManifestVersionError(ManifestError):
    """Raised when a manifest declares an unsupported manifest_version."""

    def __init__(self, path: Path, version: object, expected: str) -> None:
        self.path = path
        self.version = version
        self.expected = expected
        super().__init__(
            f"{path}: unsupported manifest_version {version!r}; expected {expected!r}"
        )


class ManifestValidationError(ManifestError):
    """Raised when a manifest violates the schema contract."""

    def __init__(self, path: Path, detail: str) -> None:
        self.path = path
        self.detail = detail
        super().__init__(f"{path}: {detail}")
