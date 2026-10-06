"""gRPC adapter for the vendor-neutral Motor domain contract."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import TypeVar

import grpc

from hiyelx.components import Motor, MotorCommand, MotorState
from hiyelx.resources import LifecycleState, ResourceIdentity
from hiyelx.rpc.errors import (
    InvalidRpcIdentityError,
    ResourceNotMotorError,
    RuntimeNotRunningError,
)
from hiyelx.rpc.generated import motor_pb2, motor_pb2_grpc
from hiyelx.rpc.status import status_for_error
from hiyelx.runtime import RuntimeManager, RuntimeManagerState

ResponseT = TypeVar("ResponseT")
RequestT = TypeVar("RequestT")

_LIFECYCLE_STATES = {
    LifecycleState.CREATED: motor_pb2.RESOURCE_LIFECYCLE_STATE_CREATED,
    LifecycleState.STARTING: motor_pb2.RESOURCE_LIFECYCLE_STATE_STARTING,
    LifecycleState.RUNNING: motor_pb2.RESOURCE_LIFECYCLE_STATE_RUNNING,
    LifecycleState.STOPPING: motor_pb2.RESOURCE_LIFECYCLE_STATE_STOPPING,
    LifecycleState.STOPPED: motor_pb2.RESOURCE_LIFECYCLE_STATE_STOPPED,
    LifecycleState.FAILED: motor_pb2.RESOURCE_LIFECYCLE_STATE_FAILED,
}


class MotorService(motor_pb2_grpc.MotorServiceServicer):
    """Translate versioned motor RPCs to one existing RuntimeManager."""

    def __init__(self, runtime: RuntimeManager) -> None:
        self._runtime = runtime

    async def ListMotors(
        self,
        request: motor_pb2.ListMotorsRequest,
        context: grpc.aio.ServicerContext[
            motor_pb2.ListMotorsRequest, motor_pb2.ListMotorsResponse
        ],
    ) -> motor_pb2.ListMotorsResponse:
        del request

        async def operation() -> motor_pb2.ListMotorsResponse:
            self._require_running_runtime()
            motors: list[motor_pb2.MotorSummary] = []
            for identity in sorted(self._runtime.startup_plan, key=str):
                resource = self._runtime.get_resource(identity)
                if isinstance(resource, Motor):
                    motors.append(
                        motor_pb2.MotorSummary(
                            identity=identity.value,
                            lifecycle_state=_LIFECYCLE_STATES[resource.state],
                        )
                    )
            return motor_pb2.ListMotorsResponse(motors=motors)

        return await self._handle(context, operation)

    async def GetMotorState(
        self,
        request: motor_pb2.GetMotorStateRequest,
        context: grpc.aio.ServicerContext[
            motor_pb2.GetMotorStateRequest, motor_pb2.GetMotorStateResponse
        ],
    ) -> motor_pb2.GetMotorStateResponse:
        async def operation() -> motor_pb2.GetMotorStateResponse:
            self._require_running_runtime()
            motor = self._get_motor(request.identity)
            state = await motor.read_state()
            return motor_pb2.GetMotorStateResponse(state=self._state_message(motor, state))

        return await self._handle(context, operation)

    async def ApplyMotorCommand(
        self,
        request: motor_pb2.ApplyMotorCommandRequest,
        context: grpc.aio.ServicerContext[
            motor_pb2.ApplyMotorCommandRequest,
            motor_pb2.ApplyMotorCommandResponse,
        ],
    ) -> motor_pb2.ApplyMotorCommandResponse:
        async def operation() -> motor_pb2.ApplyMotorCommandResponse:
            self._require_running_runtime()
            motor = self._get_motor(request.identity)
            command = MotorCommand(request.angular_velocity_radians_per_second)
            await motor.apply_command(command)
            state = await motor.read_state()
            return motor_pb2.ApplyMotorCommandResponse(state=self._state_message(motor, state))

        return await self._handle(context, operation)

    async def StopMotor(
        self,
        request: motor_pb2.StopMotorRequest,
        context: grpc.aio.ServicerContext[motor_pb2.StopMotorRequest, motor_pb2.StopMotorResponse],
    ) -> motor_pb2.StopMotorResponse:
        async def operation() -> motor_pb2.StopMotorResponse:
            self._require_running_runtime()
            motor = self._get_motor(request.identity)
            await motor.stop()
            state = await motor.read_state()
            return motor_pb2.StopMotorResponse(state=self._state_message(motor, state))

        return await self._handle(context, operation)

    async def _handle(
        self,
        context: grpc.aio.ServicerContext[RequestT, ResponseT],
        operation: Callable[[], Awaitable[ResponseT]],
    ) -> ResponseT:
        try:
            return await operation()
        except Exception as error:
            status = status_for_error(error)
            await context.abort(status.code, status.detail)
            raise AssertionError("gRPC abort returned unexpectedly") from error

    def _require_running_runtime(self) -> None:
        if self._runtime.state is not RuntimeManagerState.RUNNING:
            raise RuntimeNotRunningError(self._runtime.state)

    def _get_motor(self, value: str) -> Motor:
        try:
            identity = ResourceIdentity(value)
        except ValueError as error:
            raise InvalidRpcIdentityError(value) from error
        resource = self._runtime.get_resource(identity)
        if not isinstance(resource, Motor):
            raise ResourceNotMotorError(identity)
        return resource

    @staticmethod
    def _state_message(motor: Motor, state: MotorState) -> motor_pb2.MotorState:
        return motor_pb2.MotorState(
            identity=motor.identity.value,
            angular_position_radians=state.angular_position_radians,
            angular_velocity_radians_per_second=(state.angular_velocity_radians_per_second),
            lifecycle_state=_LIFECYCLE_STATES[motor.state],
        )
