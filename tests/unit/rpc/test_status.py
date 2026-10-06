import grpc

from hiyelx.components import InvalidMotorCommandError, MotorUnavailableError
from hiyelx.resources import (
    BackendUnavailableError,
    LifecycleState,
    OperationDeadlineExceeded,
    OperationTimeoutDetails,
    ResourceIdentity,
)
from hiyelx.rpc import (
    InvalidRpcIdentityError,
    ResourceNotMotorError,
    RuntimeNotRunningError,
    status_for_error,
)
from hiyelx.runtime import RuntimeManagerState, UnknownOwnedResourceError


def test_expected_failures_have_deterministic_statuses() -> None:
    identity = ResourceIdentity("left_motor")
    cases = (
        (InvalidRpcIdentityError(" "), grpc.StatusCode.INVALID_ARGUMENT),
        (InvalidMotorCommandError(float("nan")), grpc.StatusCode.INVALID_ARGUMENT),
        (UnknownOwnedResourceError(identity), grpc.StatusCode.NOT_FOUND),
        (ResourceNotMotorError(identity), grpc.StatusCode.FAILED_PRECONDITION),
        (
            MotorUnavailableError(identity, LifecycleState.STOPPED),
            grpc.StatusCode.FAILED_PRECONDITION,
        ),
        (RuntimeNotRunningError(RuntimeManagerState.NEW), grpc.StatusCode.UNAVAILABLE),
    )

    for error, expected in cases:
        assert status_for_error(error).code is expected


def test_unexpected_failure_is_concealed() -> None:
    status = status_for_error(RuntimeError("secret /tmp/config.yaml"))

    assert status.code is grpc.StatusCode.INTERNAL
    assert status.detail == "internal server error"
    assert "secret" not in status.detail


def test_reliability_failures_have_stable_sanitized_statuses() -> None:
    identity = ResourceIdentity("left_motor")
    timeout = OperationDeadlineExceeded(
        OperationTimeoutDetails(
            identity=identity,
            operation="motor_command",
            configured_timeout_seconds=3.0,
            lifecycle_state=LifecycleState.RUNNING,
        )
    )
    unavailable = BackendUnavailableError("SDK -1001 /dev/private")

    timeout_status = status_for_error(timeout)
    unavailable_status = status_for_error(unavailable)

    assert timeout_status.code is grpc.StatusCode.DEADLINE_EXCEEDED
    assert timeout_status.detail == "operation deadline exceeded"
    assert unavailable_status.code is grpc.StatusCode.UNAVAILABLE
    assert unavailable_status.detail == "resource backend is unavailable"
    assert "SDK" not in unavailable_status.detail
    assert "/dev" not in unavailable_status.detail
