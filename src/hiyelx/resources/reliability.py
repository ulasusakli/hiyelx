"""Vendor-neutral operation deadline and backend-failure contracts."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable
from dataclasses import dataclass, fields
from math import isfinite
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from hiyelx.resources._resource import LifecycleState, ResourceIdentity

class ReliabilityError(Exception):
    """Base class for stable RB-1 domain failures."""


class InvalidDeadlineError(ReliabilityError, ValueError):
    """Raised before work begins when a deadline is not positive and finite."""

    def __init__(self, field: str, value: object) -> None:
        self.field = field
        self.value = value
        super().__init__(f"deadline {field} must be positive and finite")


@dataclass(frozen=True, slots=True)
class OperationDeadlinePolicy:
    """Immutable seconds-based deadlines for operations HIYELX already owns."""

    startup_seconds: float = 20.0
    shutdown_seconds: float = 10.0
    motor_command_seconds: float = 3.0
    motor_state_read_seconds: float = 3.0
    transport_operation_seconds: float = 2.0

    def __post_init__(self) -> None:
        for field in fields(self):
            value = getattr(self, field.name)
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not isfinite(value)
                or value <= 0.0
            ):
                raise InvalidDeadlineError(field.name, value)
            object.__setattr__(self, field.name, float(value))


DEFAULT_OPERATION_DEADLINES = OperationDeadlinePolicy()


@dataclass(frozen=True, slots=True)
class OperationTimeoutDetails:
    """Immutable, client-safe context for one deadline expiry."""

    identity: ResourceIdentity
    operation: str
    configured_timeout_seconds: float
    lifecycle_state: LifecycleState


class OperationDeadlineExceeded(ReliabilityError):
    """Raised when an owned operation does not finish before its deadline."""

    def __init__(self, details: OperationTimeoutDetails) -> None:
        self.details = details
        super().__init__(
            f"resource {details.identity!s} exceeded the deadline for "
            f"{details.operation}"
        )

    @property
    def identity(self) -> ResourceIdentity:
        return self.details.identity

    @property
    def operation(self) -> str:
        return self.details.operation

    @property
    def configured_timeout_seconds(self) -> float:
        return self.details.configured_timeout_seconds

    @property
    def lifecycle_state(self) -> LifecycleState:
        return self.details.lifecycle_state


class BackendUnavailableError(ReliabilityError):
    """Marker for an expected communication or backend availability failure."""


async def await_with_deadline[ResultT](
    operation: Awaitable[ResultT],
    *,
    identity: ResourceIdentity,
    operation_name: str,
    timeout_seconds: float,
    lifecycle_state: LifecycleState,
) -> ResultT:
    """Await one operation and translate only expiry into a typed failure."""
    try:
        async with asyncio.timeout(timeout_seconds):
            return await operation
    except TimeoutError as error:
        details = OperationTimeoutDetails(
            identity=identity,
            operation=operation_name,
            configured_timeout_seconds=timeout_seconds,
            lifecycle_state=lifecycle_state,
        )
        raise OperationDeadlineExceeded(details) from error
