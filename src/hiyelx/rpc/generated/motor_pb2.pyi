from google.protobuf.internal import containers as _containers
from google.protobuf.internal import enum_type_wrapper as _enum_type_wrapper
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from collections.abc import Iterable as _Iterable, Mapping as _Mapping
from typing import ClassVar as _ClassVar, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class ResourceLifecycleState(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    RESOURCE_LIFECYCLE_STATE_UNSPECIFIED: _ClassVar[ResourceLifecycleState]
    RESOURCE_LIFECYCLE_STATE_CREATED: _ClassVar[ResourceLifecycleState]
    RESOURCE_LIFECYCLE_STATE_STARTING: _ClassVar[ResourceLifecycleState]
    RESOURCE_LIFECYCLE_STATE_RUNNING: _ClassVar[ResourceLifecycleState]
    RESOURCE_LIFECYCLE_STATE_STOPPING: _ClassVar[ResourceLifecycleState]
    RESOURCE_LIFECYCLE_STATE_STOPPED: _ClassVar[ResourceLifecycleState]
    RESOURCE_LIFECYCLE_STATE_FAILED: _ClassVar[ResourceLifecycleState]
RESOURCE_LIFECYCLE_STATE_UNSPECIFIED: ResourceLifecycleState
RESOURCE_LIFECYCLE_STATE_CREATED: ResourceLifecycleState
RESOURCE_LIFECYCLE_STATE_STARTING: ResourceLifecycleState
RESOURCE_LIFECYCLE_STATE_RUNNING: ResourceLifecycleState
RESOURCE_LIFECYCLE_STATE_STOPPING: ResourceLifecycleState
RESOURCE_LIFECYCLE_STATE_STOPPED: ResourceLifecycleState
RESOURCE_LIFECYCLE_STATE_FAILED: ResourceLifecycleState

class MotorSummary(_message.Message):
    __slots__ = ("identity", "lifecycle_state")
    IDENTITY_FIELD_NUMBER: _ClassVar[int]
    LIFECYCLE_STATE_FIELD_NUMBER: _ClassVar[int]
    identity: str
    lifecycle_state: ResourceLifecycleState
    def __init__(self, identity: _Optional[str] = ..., lifecycle_state: _Optional[_Union[ResourceLifecycleState, str]] = ...) -> None: ...

class MotorState(_message.Message):
    __slots__ = ("identity", "angular_position_radians", "angular_velocity_radians_per_second", "lifecycle_state")
    IDENTITY_FIELD_NUMBER: _ClassVar[int]
    ANGULAR_POSITION_RADIANS_FIELD_NUMBER: _ClassVar[int]
    ANGULAR_VELOCITY_RADIANS_PER_SECOND_FIELD_NUMBER: _ClassVar[int]
    LIFECYCLE_STATE_FIELD_NUMBER: _ClassVar[int]
    identity: str
    angular_position_radians: float
    angular_velocity_radians_per_second: float
    lifecycle_state: ResourceLifecycleState
    def __init__(self, identity: _Optional[str] = ..., angular_position_radians: _Optional[float] = ..., angular_velocity_radians_per_second: _Optional[float] = ..., lifecycle_state: _Optional[_Union[ResourceLifecycleState, str]] = ...) -> None: ...

class ListMotorsRequest(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...

class ListMotorsResponse(_message.Message):
    __slots__ = ("motors",)
    MOTORS_FIELD_NUMBER: _ClassVar[int]
    motors: _containers.RepeatedCompositeFieldContainer[MotorSummary]
    def __init__(self, motors: _Optional[_Iterable[_Union[MotorSummary, _Mapping]]] = ...) -> None: ...

class GetMotorStateRequest(_message.Message):
    __slots__ = ("identity",)
    IDENTITY_FIELD_NUMBER: _ClassVar[int]
    identity: str
    def __init__(self, identity: _Optional[str] = ...) -> None: ...

class GetMotorStateResponse(_message.Message):
    __slots__ = ("state",)
    STATE_FIELD_NUMBER: _ClassVar[int]
    state: MotorState
    def __init__(self, state: _Optional[_Union[MotorState, _Mapping]] = ...) -> None: ...

class ApplyMotorCommandRequest(_message.Message):
    __slots__ = ("identity", "angular_velocity_radians_per_second")
    IDENTITY_FIELD_NUMBER: _ClassVar[int]
    ANGULAR_VELOCITY_RADIANS_PER_SECOND_FIELD_NUMBER: _ClassVar[int]
    identity: str
    angular_velocity_radians_per_second: float
    def __init__(self, identity: _Optional[str] = ..., angular_velocity_radians_per_second: _Optional[float] = ...) -> None: ...

class ApplyMotorCommandResponse(_message.Message):
    __slots__ = ("state",)
    STATE_FIELD_NUMBER: _ClassVar[int]
    state: MotorState
    def __init__(self, state: _Optional[_Union[MotorState, _Mapping]] = ...) -> None: ...

class StopMotorRequest(_message.Message):
    __slots__ = ("identity",)
    IDENTITY_FIELD_NUMBER: _ClassVar[int]
    identity: str
    def __init__(self, identity: _Optional[str] = ...) -> None: ...

class StopMotorResponse(_message.Message):
    __slots__ = ("state",)
    STATE_FIELD_NUMBER: _ClassVar[int]
    state: MotorState
    def __init__(self, state: _Optional[_Union[MotorState, _Mapping]] = ...) -> None: ...
