"""Deterministic local ownership and lifecycle boundary."""

from collections.abc import Mapping
from types import MappingProxyType
from typing import Any

from hiyelx.components import Motor
from hiyelx.config import RuntimeConfig
from hiyelx.config.v2 import RobotConfig
from hiyelx.core import Component, ComponentCategory, ComponentRegistry
from hiyelx.models import ModelRegistry
from hiyelx.resources import (
    HealthStatus,
    LifecycleState,
    Resource,
    ResourceFaultKind,
    ResourceIdentity,
    ResourceOperation,
)
from hiyelx.runtime.errors import (
    InvalidRuntimeManagerStateError,
    ResourceIdentityMismatchError,
    RollbackFailure,
    RuntimeConstructionError,
    RuntimeSafeStopError,
    RuntimeShutdownError,
    RuntimeStartupError,
    SafeStopOutcome,
    SafeStopReport,
    ShutdownFailure,
    UnknownOwnedResourceError,
)
from hiyelx.runtime.events import (
    RuntimeEvent,
    RuntimeEventOperation,
    RuntimeEventOutcome,
    RuntimeEventSink,
)
from hiyelx.runtime.planning import plan_startup
from hiyelx.runtime.state import RuntimeManagerOperation, RuntimeManagerState


class RuntimeManager:
    """Single-use owner of configured local resources."""

    def __init__(
        self,
        config: RuntimeConfig | RobotConfig,
        registry: ModelRegistry | ComponentRegistry,
        *,
        event_sink: RuntimeEventSink | None = None,
    ) -> None:
        self._state = RuntimeManagerState.NEW
        self._startup_plan = plan_startup(config)
        if isinstance(config, RobotConfig):
            definitions: Mapping[ResourceIdentity, Any] = {
                component.id: component for component in config.components
            }
        else:
            definitions = {definition.identity: definition for definition in config.resources}
        resources: dict[ResourceIdentity, Resource] = {}

        for identity in self._startup_plan:
            definition = definitions[identity]
            try:
                resource = registry.create(definition)
                if resource.identity != identity:
                    raise ResourceIdentityMismatchError(identity, resource.identity)
            except Exception as error:
                raise RuntimeConstructionError(identity, definition.model) from error
            resources[identity] = resource

        self._resources = resources
        self._owned_resources = MappingProxyType(resources.copy())
        self._successful_start_order: tuple[ResourceIdentity, ...] = ()
        self._active_started: tuple[ResourceIdentity, ...] = ()
        self._event_sink = event_sink
        self._event_sequence = 0
        self._safe_stop_report: SafeStopReport | None = None

    @property
    def state(self) -> RuntimeManagerState:
        """Return the manager lifecycle state."""
        return self._state

    @property
    def startup_plan(self) -> tuple[ResourceIdentity, ...]:
        """Return the immutable deterministic startup plan."""
        return self._startup_plan

    @property
    def successful_start_order(self) -> tuple[ResourceIdentity, ...]:
        """Return the immutable historical order of completed starts."""
        return self._successful_start_order

    @property
    def active_resource_order(self) -> tuple[ResourceIdentity, ...]:
        """Return successfully started resources that are still running."""
        return tuple(
            identity
            for identity in self._active_started
            if self._resources[identity].state is LifecycleState.RUNNING
        )

    @property
    def owned_resources(self) -> Mapping[ResourceIdentity, Resource]:
        """Return an immutable mapping snapshot of all owned resources."""
        return self._owned_resources

    def get_resource(self, identity: ResourceIdentity) -> Resource:
        """Return one owned resource or raise a typed lookup error."""
        try:
            return self._resources[identity]
        except KeyError as error:
            raise UnknownOwnedResourceError(identity) from error

    async def start(self) -> None:
        """Start all resources sequentially in dependency order."""
        self._require_state(RuntimeManagerOperation.START, RuntimeManagerState.NEW)
        self._emit(
            operation=RuntimeEventOperation.RUNTIME_START,
            outcome=RuntimeEventOutcome.REQUESTED,
            summary="runtime start requested",
        )
        self._state = RuntimeManagerState.STARTING
        started: list[ResourceIdentity] = []

        for identity in self._startup_plan:
            resource = self._resources[identity]
            self._emit_resource(
                resource,
                operation=RuntimeEventOperation.RESOURCE_START,
                outcome=RuntimeEventOutcome.ATTEMPTED,
                summary="resource start attempted",
            )
            try:
                await resource.start()
            except Exception as error:
                self._emit_resource(
                    resource,
                    operation=RuntimeEventOperation.RESOURCE_START,
                    outcome=RuntimeEventOutcome.FAILED,
                    summary="resource start failed",
                )
                rollback_failures = await self._rollback(started)
                self._active_started = ()
                self._state = RuntimeManagerState.FAILED
                self._emit(
                    operation=RuntimeEventOperation.RUNTIME_FAILED,
                    outcome=RuntimeEventOutcome.FAILED,
                    summary="runtime failed during startup",
                )
                raise RuntimeStartupError(
                    identity,
                    error,
                    rollback_failures,
                ) from error
            started.append(identity)
            self._successful_start_order = tuple(started)
            self._active_started = tuple(started)
            self._emit_resource(
                resource,
                operation=RuntimeEventOperation.RESOURCE_START,
                outcome=RuntimeEventOutcome.SUCCEEDED,
                summary="resource start succeeded",
            )

        self._state = RuntimeManagerState.RUNNING
        self._emit(
            operation=RuntimeEventOperation.RUNTIME_RUNNING,
            outcome=RuntimeEventOutcome.SUCCEEDED,
            summary="runtime running",
        )

    async def shutdown(self) -> None:
        """Stop every started resource sequentially in reverse startup order."""
        self._require_state(RuntimeManagerOperation.SHUTDOWN, RuntimeManagerState.RUNNING)
        self._emit(
            operation=RuntimeEventOperation.RUNTIME_SHUTDOWN,
            outcome=RuntimeEventOutcome.REQUESTED,
            summary="runtime shutdown requested",
        )
        self._state = RuntimeManagerState.STOPPING
        failures: list[ShutdownFailure] = []

        for identity in reversed(self._active_started):
            resource = self._resources[identity]
            self._emit_resource(
                resource,
                operation=RuntimeEventOperation.RESOURCE_SHUTDOWN,
                outcome=RuntimeEventOutcome.ATTEMPTED,
                summary="resource shutdown attempted",
            )
            try:
                await resource.shutdown()
            except Exception as error:
                failures.append(ShutdownFailure(identity, error))
                self._emit_resource(
                    resource,
                    operation=RuntimeEventOperation.RESOURCE_SHUTDOWN,
                    outcome=RuntimeEventOutcome.FAILED,
                    summary="resource shutdown failed",
                )
            else:
                self._emit_resource(
                    resource,
                    operation=RuntimeEventOperation.RESOURCE_SHUTDOWN,
                    outcome=RuntimeEventOutcome.SUCCEEDED,
                    summary="resource shutdown succeeded",
                )

        self._active_started = ()
        if failures:
            self._state = RuntimeManagerState.FAILED
            self._emit(
                operation=RuntimeEventOperation.RUNTIME_FAILED,
                outcome=RuntimeEventOutcome.FAILED,
                summary="runtime failed during shutdown",
            )
            shutdown_error = RuntimeShutdownError(tuple(failures))
            raise shutdown_error from failures[0].error
        self._state = RuntimeManagerState.STOPPED
        self._emit(
            operation=RuntimeEventOperation.RUNTIME_STOPPED,
            outcome=RuntimeEventOutcome.SUCCEEDED,
            summary="runtime stopped",
        )

    async def safe_stop(
        self,
        *,
        primary_failure: Exception | None = None,
    ) -> SafeStopReport:
        """Best-effort stop active motors once, preserving a triggering fault."""
        self._require_state(RuntimeManagerOperation.SAFE_STOP, RuntimeManagerState.RUNNING)
        self._emit(
            operation=RuntimeEventOperation.SAFE_STOP,
            outcome=RuntimeEventOutcome.REQUESTED,
            summary="safe-stop requested",
        )

        if self._safe_stop_report is None:
            outcomes: list[SafeStopOutcome] = []
            for identity in reversed(self._successful_start_order):
                resource = self._resources[identity]
                if resource.state is not LifecycleState.RUNNING:
                    continue
                is_motor = isinstance(resource, Motor)
                is_actuator = (
                    isinstance(resource, Component)
                    and resource.category is ComponentCategory.ACTUATOR
                )
                if not (is_motor or is_actuator):
                    continue
                self._emit_resource(
                    resource,
                    operation=RuntimeEventOperation.SAFE_STOP,
                    outcome=RuntimeEventOutcome.ATTEMPTED,
                    summary="motor safe-stop attempted",
                )
                try:
                    if isinstance(resource, Motor):
                        await resource.stop()
                    elif isinstance(resource, Component):
                        await resource.safe_stop()
                except Exception as error:
                    resource.record_fault(
                        ResourceFaultKind.SAFE_STOP,
                        ResourceOperation.SAFE_STOP,
                    )
                    outcomes.append(SafeStopOutcome(identity, False, error))
                    self._emit_resource(
                        resource,
                        operation=RuntimeEventOperation.HEALTH_DEGRADATION,
                        outcome=RuntimeEventOutcome.FAILED,
                        summary="resource health degraded after safe-stop failure",
                    )
                    self._emit_resource(
                        resource,
                        operation=RuntimeEventOperation.SAFE_STOP,
                        outcome=RuntimeEventOutcome.FAILED,
                        summary="motor safe-stop failed",
                    )
                else:
                    outcomes.append(SafeStopOutcome(identity, True))
                    self._emit_resource(
                        resource,
                        operation=RuntimeEventOperation.SAFE_STOP,
                        outcome=RuntimeEventOutcome.SUCCEEDED,
                        summary="motor safe-stop succeeded",
                    )
            self._safe_stop_report = SafeStopReport(tuple(outcomes))

        report = self._safe_stop_report
        self._emit(
            operation=RuntimeEventOperation.SAFE_STOP_CLEANUP,
            outcome=RuntimeEventOutcome.COMPLETED,
            summary="safe-stop cleanup completed",
        )
        if primary_failure is not None or report.failures:
            safe_stop_error = RuntimeSafeStopError(report, primary_failure)
            cause = primary_failure
            if cause is None:
                cause = report.failures[0].error
            raise safe_stop_error from cause
        return report

    async def _rollback(
        self,
        started: list[ResourceIdentity],
    ) -> tuple[RollbackFailure, ...]:
        self._emit(
            operation=RuntimeEventOperation.STARTUP_ROLLBACK,
            outcome=RuntimeEventOutcome.ATTEMPTED,
            summary="startup rollback attempted",
        )
        failures: list[RollbackFailure] = []
        for identity in reversed(started):
            resource = self._resources[identity]
            self._emit_resource(
                resource,
                operation=RuntimeEventOperation.RESOURCE_SHUTDOWN,
                outcome=RuntimeEventOutcome.ATTEMPTED,
                summary="resource shutdown attempted during startup rollback",
            )
            try:
                await resource.shutdown()
            except Exception as error:
                failures.append(RollbackFailure(identity, error))
                self._emit_resource(
                    resource,
                    operation=RuntimeEventOperation.RESOURCE_SHUTDOWN,
                    outcome=RuntimeEventOutcome.FAILED,
                    summary="resource shutdown failed during startup rollback",
                )
            else:
                self._emit_resource(
                    resource,
                    operation=RuntimeEventOperation.RESOURCE_SHUTDOWN,
                    outcome=RuntimeEventOutcome.SUCCEEDED,
                    summary="resource shutdown succeeded during startup rollback",
                )
        self._emit(
            operation=RuntimeEventOperation.STARTUP_ROLLBACK,
            outcome=RuntimeEventOutcome.COMPLETED,
            summary="startup rollback completed",
        )
        return tuple(failures)

    def _emit_resource(
        self,
        resource: Resource,
        *,
        operation: RuntimeEventOperation,
        outcome: RuntimeEventOutcome,
        summary: str,
    ) -> None:
        self._emit(
            operation=operation,
            outcome=outcome,
            summary=summary,
            identity=resource.identity,
            lifecycle_state=resource.state,
            health_status=resource.health.status,
        )

    def _emit(
        self,
        *,
        operation: RuntimeEventOperation,
        outcome: RuntimeEventOutcome,
        summary: str,
        identity: ResourceIdentity | None = None,
        lifecycle_state: LifecycleState | None = None,
        health_status: HealthStatus | None = None,
    ) -> None:
        if self._event_sink is None:
            return
        event = RuntimeEvent(
            sequence=self._event_sequence,
            operation=operation,
            outcome=outcome,
            summary=summary,
            identity=identity,
            lifecycle_state=lifecycle_state,
            health_status=health_status,
        )
        self._event_sequence += 1
        self._event_sink.record(event)

    def _require_state(
        self,
        operation: RuntimeManagerOperation,
        required_state: RuntimeManagerState,
    ) -> None:
        if self.state is not required_state:
            raise InvalidRuntimeManagerStateError(
                self.state,
                operation,
                required_state,
            )
