"""Deterministic local ownership and lifecycle boundary."""

from collections.abc import Mapping
from types import MappingProxyType

from hiyelx.config import RuntimeConfig
from hiyelx.models import ModelRegistry
from hiyelx.resources import Resource, ResourceIdentity
from hiyelx.runtime.errors import (
    InvalidRuntimeManagerStateError,
    ResourceIdentityMismatchError,
    RollbackFailure,
    RuntimeConstructionError,
    RuntimeShutdownError,
    RuntimeStartupError,
    ShutdownFailure,
    UnknownOwnedResourceError,
)
from hiyelx.runtime.planning import plan_startup
from hiyelx.runtime.state import RuntimeManagerOperation, RuntimeManagerState


class RuntimeManager:
    """Single-use owner of configured local resources."""

    def __init__(self, config: RuntimeConfig, registry: ModelRegistry) -> None:
        self._state = RuntimeManagerState.NEW
        self._startup_plan = plan_startup(config)
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
        self._state = RuntimeManagerState.STARTING
        started: list[ResourceIdentity] = []

        for identity in self._startup_plan:
            resource = self._resources[identity]
            try:
                await resource.start()
            except Exception as error:
                rollback_failures = await self._rollback(started)
                self._active_started = ()
                self._state = RuntimeManagerState.FAILED
                raise RuntimeStartupError(
                    identity,
                    error,
                    rollback_failures,
                ) from error
            started.append(identity)
            self._successful_start_order = tuple(started)
            self._active_started = tuple(started)

        self._state = RuntimeManagerState.RUNNING

    async def shutdown(self) -> None:
        """Stop every started resource sequentially in reverse startup order."""
        self._require_state(RuntimeManagerOperation.SHUTDOWN, RuntimeManagerState.RUNNING)
        self._state = RuntimeManagerState.STOPPING
        failures: list[ShutdownFailure] = []

        for identity in reversed(self._active_started):
            try:
                await self._resources[identity].shutdown()
            except Exception as error:
                failures.append(ShutdownFailure(identity, error))

        self._active_started = ()
        if failures:
            self._state = RuntimeManagerState.FAILED
            shutdown_error = RuntimeShutdownError(tuple(failures))
            raise shutdown_error from failures[0].error
        self._state = RuntimeManagerState.STOPPED

    async def _rollback(
        self,
        started: list[ResourceIdentity],
    ) -> tuple[RollbackFailure, ...]:
        failures: list[RollbackFailure] = []
        for identity in reversed(started):
            try:
                await self._resources[identity].shutdown()
            except Exception as error:
                failures.append(RollbackFailure(identity, error))
        return tuple(failures)

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
