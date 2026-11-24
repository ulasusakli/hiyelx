"""Deterministic version compatibility checking and manifest dependency resolution."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum

from hiyelx.manifests.models import ComponentManifest

_VERSION_RE = re.compile(
    r"^(?P<major>0|[1-9]\d*)\.(?P<minor>0|[1-9]\d*)\.(?P<patch>0|[1-9]\d*)"
    r"(?:(?P<pre_tag>a|b|rc)(?P<pre_num>\d+))?$"
)
_PRE_RANK = {"a": 0, "b": 1, "rc": 2}


class CompatibilityStatus(StrEnum):
    """Outcome of checking one manifest against a target Runtime and catalog."""

    COMPATIBLE = "compatible"
    INCOMPATIBLE_RUNTIME = "incompatible_runtime"
    MISSING_DEPENDENCY = "missing_dependency"
    INCOMPATIBLE_DEPENDENCY = "incompatible_dependency"
    DEPENDENCY_CYCLE = "dependency_cycle"


@dataclass(frozen=True, slots=True)
class CompatibilityIssue:
    """One structured compatibility or dependency resolution diagnostic."""

    code: CompatibilityStatus
    message: str
    target_id: str | None = None


@dataclass(frozen=True, slots=True)
class CompatibilityReport:
    """Immutable compatibility verdict for one ComponentManifest."""

    manifest_id: str
    runtime_version: str
    compatible: bool
    status: CompatibilityStatus
    issues: tuple[CompatibilityIssue, ...]
    resolved_order: tuple[str, ...]


def parse_version_key(version: str) -> tuple[int, int, int, int, int]:
    """Convert ``MAJOR.MINOR.PATCH[a|b|rcN]`` into a total-order comparison key.

    Final releases rank higher than pre-releases of the same base version:
    ``0.2.0a1 < 0.2.0b1 < 0.2.0rc1 < 0.2.0``.
    """
    match = _VERSION_RE.fullmatch(version)
    if match is None:
        msg = f"invalid version string {version!r}"
        raise ValueError(msg)
    major = int(match.group("major"))
    minor = int(match.group("minor"))
    patch = int(match.group("patch"))
    pre_tag = match.group("pre_tag")
    if pre_tag is None:
        return (major, minor, patch, 3, 0)
    return (major, minor, patch, _PRE_RANK[pre_tag], int(match.group("pre_num")))


def check_manifest_compatibility(
    manifest: ComponentManifest,
    *,
    runtime_version: str,
    catalog: Mapping[str, ComponentManifest] | None = None,
) -> CompatibilityReport:
    """Evaluate Runtime version bounds and transitive dependencies for ``manifest``."""
    available: dict[str, ComponentManifest] = dict(catalog or {})
    available[manifest.id] = manifest
    issues: list[CompatibilityIssue] = []

    rt_key = parse_version_key(runtime_version)
    min_key = parse_version_key(manifest.runtime.min_version)
    if rt_key < min_key:
        issues.append(
            CompatibilityIssue(
                code=CompatibilityStatus.INCOMPATIBLE_RUNTIME,
                target_id=manifest.id,
                message=(
                    f"{manifest.id} requires runtime >= {manifest.runtime.min_version}, "
                    f"found {runtime_version}"
                ),
            )
        )
    if manifest.runtime.max_version is not None:
        max_key = parse_version_key(manifest.runtime.max_version)
        if rt_key > max_key:
            issues.append(
                CompatibilityIssue(
                    code=CompatibilityStatus.INCOMPATIBLE_RUNTIME,
                    target_id=manifest.id,
                    message=(
                        f"{manifest.id} requires runtime <= {manifest.runtime.max_version}, "
                        f"found {runtime_version}"
                    ),
                )
            )

    resolved_order: list[str] = []
    visiting: list[str] = []
    visited: set[str] = set()

    def resolve(current: ComponentManifest) -> None:
        if current.id in visited:
            return
        if current.id in visiting:
            start = visiting.index(current.id)
            chain = " -> ".join((*visiting[start:], current.id))
            issues.append(
                CompatibilityIssue(
                    code=CompatibilityStatus.DEPENDENCY_CYCLE,
                    target_id=current.id,
                    message=f"manifest dependency cycle detected: {chain}",
                )
            )
            return

        visiting.append(current.id)
        for dep in current.dependencies:
            dep_manifest = available.get(dep.id)
            if dep_manifest is None:
                issues.append(
                    CompatibilityIssue(
                        code=CompatibilityStatus.MISSING_DEPENDENCY,
                        target_id=dep.id,
                        message=f"{current.id} requires missing dependency {dep.id!r}",
                    )
                )
                continue
            if dep.min_version is not None and (
                parse_version_key(dep_manifest.version) < parse_version_key(dep.min_version)
            ):
                issues.append(
                    CompatibilityIssue(
                        code=CompatibilityStatus.INCOMPATIBLE_DEPENDENCY,
                        target_id=dep.id,
                        message=(
                            f"{current.id} requires {dep.id} >= {dep.min_version}, "
                            f"found {dep_manifest.version}"
                        ),
                    )
                )
            resolve(dep_manifest)
        visiting.pop()
        visited.add(current.id)
        resolved_order.append(current.id)

    resolve(manifest)

    if not issues:
        return CompatibilityReport(
            manifest_id=manifest.id,
            runtime_version=runtime_version,
            compatible=True,
            status=CompatibilityStatus.COMPATIBLE,
            issues=(),
            resolved_order=tuple(resolved_order),
        )
    return CompatibilityReport(
        manifest_id=manifest.id,
        runtime_version=runtime_version,
        compatible=False,
        status=issues[0].code,
        issues=tuple(issues),
        resolved_order=tuple(resolved_order),
    )
