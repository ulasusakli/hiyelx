"""Internal deterministic dependency validation and topological planning."""

from collections import Counter
from collections.abc import Mapping
from heapq import heappop, heappush

from hiyelx.config import ResourceDefinition, RuntimeConfig
from hiyelx.resources import ResourceIdentity
from hiyelx.runtime.errors import (
    DependencyCycleError,
    DuplicateDependencyError,
    MissingDependencyError,
    SelfDependencyError,
)


def plan_startup(config: RuntimeConfig) -> tuple[ResourceIdentity, ...]:
    """Return the lexicographically smallest valid topological order."""
    definitions = {definition.identity: definition for definition in config.resources}
    identities = frozenset(definitions)

    for identity in sorted(identities, key=_identity_value):
        dependencies = definitions[identity].depends_on
        counts = Counter(dependencies)
        duplicates = sorted(
            (dependency for dependency, count in counts.items() if count > 1),
            key=_identity_value,
        )
        if duplicates:
            raise DuplicateDependencyError(identity, duplicates[0])
        if identity in counts:
            raise SelfDependencyError(identity)
        missing = sorted(
            (dependency for dependency in dependencies if dependency not in identities),
            key=_identity_value,
        )
        if missing:
            raise MissingDependencyError(identity, missing[0])

    indegree = {
        identity: len(definition.depends_on)
        for identity, definition in definitions.items()
    }
    dependents: dict[ResourceIdentity, set[ResourceIdentity]] = {
        identity: set() for identity in identities
    }
    for identity, definition in definitions.items():
        for dependency in definition.depends_on:
            dependents[dependency].add(identity)

    available: list[tuple[str, ResourceIdentity]] = []
    for identity, dependency_count in indegree.items():
        if dependency_count == 0:
            heappush(available, (identity.value, identity))

    plan: list[ResourceIdentity] = []
    while available:
        _, identity = heappop(available)
        plan.append(identity)
        for dependent in sorted(dependents[identity], key=_identity_value):
            indegree[dependent] -= 1
            if indegree[dependent] == 0:
                heappush(available, (dependent.value, dependent))

    if len(plan) != len(definitions):
        unresolved = frozenset(
            identity for identity, count in indegree.items() if count > 0
        )
        raise DependencyCycleError(_find_cycle(definitions, unresolved))

    return tuple(plan)


def _identity_value(identity: ResourceIdentity) -> str:
    return identity.value


def _find_cycle(
    definitions: Mapping[ResourceIdentity, ResourceDefinition],
    unresolved: frozenset[ResourceIdentity],
) -> tuple[ResourceIdentity, ...]:
    visited: set[ResourceIdentity] = set()
    active_positions: dict[ResourceIdentity, int] = {}
    path: list[ResourceIdentity] = []

    def visit(identity: ResourceIdentity) -> tuple[ResourceIdentity, ...] | None:
        if identity in active_positions:
            cycle = path[active_positions[identity] :]
            return tuple(sorted(cycle, key=_identity_value))
        if identity in visited:
            return None

        active_positions[identity] = len(path)
        path.append(identity)
        for dependency in sorted(
            definitions[identity].depends_on,
            key=_identity_value,
        ):
            if dependency not in unresolved:
                continue
            cycle = visit(dependency)
            if cycle is not None:
                return cycle
        path.pop()
        active_positions.pop(identity)
        visited.add(identity)
        return None

    for identity in sorted(unresolved, key=_identity_value):
        cycle = visit(identity)
        if cycle is not None:
            return cycle

    raise AssertionError("unresolved dependency graph did not contain a cycle")
