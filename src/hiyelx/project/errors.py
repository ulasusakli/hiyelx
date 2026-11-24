"""Typed errors for the HIYELX Studio Project Model Engine."""

from __future__ import annotations

from pathlib import Path


class ProjectError(Exception):
    """Base error for Studio project workspace operations."""


class ProjectPathError(ProjectError):
    """Raised when a workspace path attempts traversal or symlink escape."""

    def __init__(self, path: str, reason: str) -> None:
        self.path = path
        self.reason = reason
        super().__init__(f"unsafe workspace path {path!r}: {reason}")


class ProjectLoadError(ProjectError):
    """Raised when a project file cannot be read or parsed."""

    def __init__(self, path: Path, reason: str) -> None:
        self.path = path
        self.reason = reason
        super().__init__(f"{path}: {reason}")


class UnsupportedProjectSchemaVersionError(ProjectError):
    """Raised when a project artifact declares an unsupported schema version."""

    def __init__(self, path: Path, version: object, expected: str) -> None:
        self.path = path
        self.version = version
        self.expected = expected
        super().__init__(
            f"{path}: unsupported schema_version {version!r}; expected {expected!r}"
        )


class ProjectValidationError(ProjectError):
    """Raised when a project manifest, graph, or layout fails schema validation."""

    def __init__(self, path: Path, detail: str) -> None:
        self.path = path
        self.detail = detail
        super().__init__(f"{path}: {detail}")


class GraphDependencyCycleError(ProjectValidationError):
    """Raised when lifecycle dependency edges in a robot graph form a cycle."""

    def __init__(self, path: Path, cycle: tuple[str, ...]) -> None:
        self.cycle = cycle
        chain = " -> ".join(cycle)
        super().__init__(path, f"dependency cycle detected: {chain}")


class ProjectTemplateError(ProjectError):
    """Raised when project scaffolding receives an invalid template or target."""
