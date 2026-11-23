"""Vendor-neutral Component base contract."""

from __future__ import annotations

from abc import ABC
from collections.abc import Iterable
from typing import final

from hiyelx.core.capabilities import ComponentCapability
from hiyelx.core.types import ComponentCategory
from hiyelx.resources import (
    DEFAULT_OPERATION_DEADLINES,
    OperationDeadlinePolicy,
    Resource,
    ResourceIdentity,
)


class Component(Resource, ABC):
    """Base class for all multi-component robotics abstractions.

    Inherits deterministic lifecycle state transitions and deadline-enforced
    execution from ``Resource``, adding explicit category taxonomy, capability
    declaration, and a safe-stop protocol.
    """

    def __init__(
        self,
        identity: ResourceIdentity,
        category: ComponentCategory,
        capabilities: Iterable[ComponentCapability] = (),
        *,
        deadline_policy: OperationDeadlinePolicy = DEFAULT_OPERATION_DEADLINES,
    ) -> None:
        super().__init__(identity, deadline_policy=deadline_policy)
        self._category = category
        self._capabilities = frozenset(capabilities)

    @property
    def category(self) -> ComponentCategory:
        """Return the broad functional category of this component."""
        return self._category

    @property
    def capabilities(self) -> frozenset[ComponentCapability]:
        """Return the immutable set of declared capabilities."""
        return self._capabilities

    @final
    def has_capability(self, capability: ComponentCapability) -> bool:
        """Return True if this component declares the specified capability."""
        return capability in self._capabilities

    async def safe_stop(self) -> None:
        """Perform a best-effort, safe cessation of active behavior.

        Default implementation is a no-op suitable for non-actuator components.
        Actuators and stateful services must override this to command zero-effort
        or safe rest states.
        """
