"""Command-line workflows for local HIYELX development."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections.abc import Sequence
from importlib.resources import as_file, files
from pathlib import Path

import grpc

from hiyelx.acceptance import (
    XL430_W250_T_ACCEPTANCE_PROFILE,
    HardwareAcceptanceError,
    load_hardware_acceptance_config,
    preflight_hardware_acceptance,
)
from hiyelx.config import ConfigurationError, RuntimeConfig, load_config
from hiyelx.drivers.dynamixel import register_dynamixel_xl430_motor
from hiyelx.models import ModelRegistry
from hiyelx.resources import ResourceIdentity
from hiyelx.rpc import MotorGrpcServer, RpcTransportState
from hiyelx.rpc.generated import motor_pb2, motor_pb2_grpc
from hiyelx.runtime import RuntimeManager, RuntimeManagerState
from hiyelx.runtime.control import (
    ControlProtocolError,
    InvalidRuntimeControlConfigurationError,
    InvalidSessionIdError,
    RuntimeCliExitCode,
    RuntimeHistoryError,
    RuntimeOwnerCleanupError,
    RuntimeOwnerStartupError,
    RuntimePreviewUnavailableError,
    RuntimePreviewUnsupportedError,
    SessionAlreadyRunningError,
    SessionNotRunningError,
    UnsafeSessionPathError,
    UnsupportedPlatformError,
    render_status,
    request_preview,
    request_status,
    request_stop,
    run_local_runtime,
    validate_session_id,
    validate_simulation_config,
)
from hiyelx.runtime.history import (
    DEFAULT_EVENT_LIMIT,
    DEFAULT_LIMIT,
    EventRecord,
    HistoryError,
    InvalidEventCursorError,
    InvalidEventLimitError,
    InvalidHistoryLimitError,
    InvalidRetentionKeepError,
    InvalidRunIdError,
    RunNotFoundError,
    RunRecord,
    get_run,
    list_events,
    list_runs,
    prune_runs,
    validate_event_cursor,
    validate_event_limit,
    validate_limit,
    validate_retention_keep,
)
from hiyelx.sdk import MotorDriverScaffoldError, create_motor_driver_scaffold
from hiyelx.simulation import (
    SimulatedMotor,
    register_simulated_motor,
    render_simulation_preview_json,
)

SUCCESS = 0
FAILURE = 1
_DEMO_IDENTITY = ResourceIdentity("sim_motor")
_POSITIVE_VELOCITY = 2.0
_POSITIVE_TIME_STEP = 1.25
_NEGATIVE_VELOCITY = -1.0
_NEGATIVE_TIME_STEP = 0.5


def main(argv: Sequence[str] | None = None) -> int:
    """Run the HIYELX command-line interface with deterministic exit codes."""
    parser = _parser()
    arguments = parser.parse_args(argv)

    if arguments.command == "validate-config":
        return _validate_config(arguments.path)
    if arguments.command == "demo" and arguments.demo == "sim-motor":
        try:
            transcript = asyncio.run(run_sim_motor_demo())
        except Exception:
            print("error: sim-motor demo failed", file=sys.stderr)
            return FAILURE
        for line in transcript:
            print(line)
        return SUCCESS
    if arguments.command == "scaffold" and arguments.scaffold == "motor-driver":
        return _scaffold_motor_driver(
            arguments.output,
            package_name=arguments.package_name,
            model_name=arguments.model_name,
        )
    if arguments.command == "hardware" and arguments.hardware == "preflight":
        return _hardware_preflight(
            arguments.path,
            physical_operation_consent=arguments.physical_consent,
        )
    if arguments.command == "runtime":
        if arguments.runtime == "start":
            return _runtime_start(arguments.path, session=arguments.session)
        if arguments.runtime == "status":
            return _runtime_status(session=arguments.session)
        if arguments.runtime == "preview":
            return _runtime_preview(session=arguments.session)
        if arguments.runtime == "stop":
            return _runtime_stop(session=arguments.session)
        if arguments.runtime == "events":
            return _runtime_events(
                arguments.run_id,
                after=arguments.after,
                limit=arguments.limit,
                as_json=arguments.json,
            )
        if arguments.runtime == "runs":
            if arguments.runs == "list":
                return _runtime_runs_list(limit=arguments.limit, as_json=arguments.json)
            if arguments.runs == "show":
                return _runtime_runs_show(arguments.run_id, as_json=arguments.json)
            if arguments.runs == "prune":
                return _runtime_runs_prune(keep=arguments.keep)

    parser.error("a command is required")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="hiyelx",
        description="HIYELX local developer workflows",
    )
    commands = parser.add_subparsers(dest="command")

    validate = commands.add_parser(
        "validate-config",
        help="validate a local HIYELX configuration",
    )
    validate.add_argument("path", type=Path)

    demo = commands.add_parser("demo", help="run a deterministic local demo")
    demos = demo.add_subparsers(dest="demo")
    demos.add_parser("sim-motor", help="run the loopback simulated-motor demo")

    scaffold = commands.add_parser(
        "scaffold",
        help="create a non-overwriting local development scaffold",
    )
    scaffolds = scaffold.add_subparsers(dest="scaffold")
    motor_driver = scaffolds.add_parser(
        "motor-driver",
        help="create a hardware-free external motor-driver starting point",
    )
    motor_driver.add_argument("output", type=Path)
    motor_driver.add_argument("--package-name", required=True)
    motor_driver.add_argument("--model-name", required=True)

    hardware = commands.add_parser(
        "hardware",
        help="run hardware-acceptance readiness workflows",
    )
    hardware_commands = hardware.add_subparsers(dest="hardware")
    preflight = hardware_commands.add_parser(
        "preflight",
        help="validate and print a sanitized hardware-acceptance plan",
    )
    preflight.add_argument("path", type=Path)
    preflight.add_argument("--physical-consent")

    runtime = commands.add_parser(
        "runtime",
        help="control one foreground local simulation runtime",
    )
    runtime_commands = runtime.add_subparsers(dest="runtime")
    runtime_start = runtime_commands.add_parser(
        "start",
        help="start and own a local runtime in the foreground",
    )
    runtime_start.add_argument("path", type=Path)
    runtime_start.add_argument("--session", required=True)
    runtime_status = runtime_commands.add_parser(
        "status",
        help="print a sanitized local runtime snapshot",
    )
    runtime_status.add_argument("--session", required=True)
    runtime_preview = runtime_commands.add_parser(
        "preview",
        help="print one canonical simulation preview snapshot",
    )
    runtime_preview.add_argument("--session", required=True)
    runtime_stop = runtime_commands.add_parser(
        "stop",
        help="request ordered safe-stop and shutdown",
    )
    runtime_stop.add_argument("--session", required=True)
    runtime_events = runtime_commands.add_parser(
        "events",
        help="inspect durable events for one runtime run",
    )
    runtime_events.add_argument("--run", dest="run_id", required=True)
    runtime_events.add_argument("--after", type=_event_after, default=-1)
    runtime_events.add_argument(
        "--limit",
        type=_event_limit,
        default=DEFAULT_EVENT_LIMIT,
    )
    runtime_events.add_argument("--json", action="store_true")
    runtime_runs = runtime_commands.add_parser(
        "runs",
        help="inspect durable local runtime runs",
    )
    runs_commands = runtime_runs.add_subparsers(dest="runs")
    runs_list = runs_commands.add_parser("list", help="list recent runtime runs")
    runs_list.add_argument("--limit", type=_history_limit, default=DEFAULT_LIMIT)
    runs_list.add_argument("--json", action="store_true")
    runs_show = runs_commands.add_parser("show", help="show one runtime run")
    runs_show.add_argument("run_id")
    runs_show.add_argument("--json", action="store_true")
    runs_prune = runs_commands.add_parser(
        "prune",
        help="delete older finalized runtime runs",
    )
    runs_prune.add_argument("--keep", required=True, type=_retention_keep)
    return parser


def _runtime_start(path: Path, *, session: str) -> int:
    try:
        validate_session_id(session)
        config = load_config(path)
        validate_simulation_config(config)
        asyncio.run(run_local_runtime(config, session, ready=_print_runtime_ready))
    except InvalidSessionIdError:
        return _runtime_failure(
            RuntimeCliExitCode.INVALID_SESSION_ID,
            "runtime session ID is invalid",
        )
    except (ConfigurationError, InvalidRuntimeControlConfigurationError):
        return _runtime_failure(
            RuntimeCliExitCode.INVALID_CONFIGURATION,
            "runtime configuration is invalid",
        )
    except SessionAlreadyRunningError:
        return _runtime_failure(
            RuntimeCliExitCode.SESSION_ALREADY_RUNNING,
            "runtime session is already running",
        )
    except UnsupportedPlatformError:
        return _runtime_failure(
            RuntimeCliExitCode.UNSUPPORTED_PLATFORM,
            "runtime control is unsupported on this platform",
        )
    except RuntimeOwnerStartupError:
        return _runtime_failure(
            RuntimeCliExitCode.RUNTIME_STARTUP_FAILURE,
            "runtime startup failed",
        )
    except RuntimeOwnerCleanupError:
        return _runtime_failure(
            RuntimeCliExitCode.RUNTIME_CLEANUP_FAILURE,
            "runtime cleanup failed",
        )
    except RuntimeHistoryError:
        return _runtime_failure(
            RuntimeCliExitCode.HISTORY_STORE_FAILURE,
            "runtime history failed",
        )
    except (ControlProtocolError, UnsafeSessionPathError, OSError):
        return _runtime_failure(
            RuntimeCliExitCode.CONTROL_PROTOCOL_FAILURE,
            "runtime control failed",
        )
    except KeyboardInterrupt:
        print("runtime=stopped")
        return RuntimeCliExitCode.SUCCESS
    print("runtime=stopped")
    return RuntimeCliExitCode.SUCCESS


def _runtime_status(*, session: str) -> int:
    try:
        reply = asyncio.run(request_status(session))
    except InvalidSessionIdError:
        return _runtime_failure(
            RuntimeCliExitCode.INVALID_SESSION_ID,
            "runtime session ID is invalid",
        )
    except SessionNotRunningError:
        return _runtime_failure(
            RuntimeCliExitCode.SESSION_NOT_RUNNING,
            "runtime session is not running",
        )
    except UnsupportedPlatformError:
        return _runtime_failure(
            RuntimeCliExitCode.UNSUPPORTED_PLATFORM,
            "runtime control is unsupported on this platform",
        )
    except (ControlProtocolError, UnsafeSessionPathError, OSError):
        return _runtime_failure(
            RuntimeCliExitCode.CONTROL_PROTOCOL_FAILURE,
            "runtime control failed",
        )
    for line in render_status(reply):
        print(line)
    return RuntimeCliExitCode.SUCCESS


def _runtime_preview(*, session: str) -> int:
    try:
        reply = asyncio.run(request_preview(session))
    except InvalidSessionIdError:
        return _runtime_failure(
            RuntimeCliExitCode.INVALID_SESSION_ID,
            "runtime session ID is invalid",
        )
    except SessionNotRunningError:
        return _runtime_failure(
            RuntimeCliExitCode.SESSION_NOT_RUNNING,
            "runtime session is not running",
        )
    except UnsupportedPlatformError:
        return _runtime_failure(
            RuntimeCliExitCode.UNSUPPORTED_PLATFORM,
            "runtime control is unsupported on this platform",
        )
    except RuntimePreviewUnavailableError:
        return _runtime_failure(
            RuntimeCliExitCode.PREVIEW_UNAVAILABLE,
            "runtime preview is unavailable",
        )
    except RuntimePreviewUnsupportedError:
        return _runtime_failure(
            RuntimeCliExitCode.PREVIEW_UNSUPPORTED,
            "runtime preview is unsupported",
        )
    except (ControlProtocolError, UnsafeSessionPathError, OSError):
        return _runtime_failure(
            RuntimeCliExitCode.CONTROL_PROTOCOL_FAILURE,
            "runtime control failed",
        )
    sys.stdout.write(render_simulation_preview_json(reply.preview))
    return RuntimeCliExitCode.SUCCESS


def _runtime_stop(*, session: str) -> int:
    try:
        reply = asyncio.run(request_stop(session))
    except InvalidSessionIdError:
        return _runtime_failure(
            RuntimeCliExitCode.INVALID_SESSION_ID,
            "runtime session ID is invalid",
        )
    except SessionNotRunningError:
        return _runtime_failure(
            RuntimeCliExitCode.SESSION_NOT_RUNNING,
            "runtime session is not running",
        )
    except UnsupportedPlatformError:
        return _runtime_failure(
            RuntimeCliExitCode.UNSUPPORTED_PLATFORM,
            "runtime control is unsupported on this platform",
        )
    except RuntimeOwnerCleanupError:
        return _runtime_failure(
            RuntimeCliExitCode.RUNTIME_CLEANUP_FAILURE,
            "runtime cleanup failed",
        )
    except RuntimeHistoryError:
        return _runtime_failure(
            RuntimeCliExitCode.HISTORY_STORE_FAILURE,
            "runtime history failed",
        )
    except (ControlProtocolError, UnsafeSessionPathError, OSError):
        return _runtime_failure(
            RuntimeCliExitCode.CONTROL_PROTOCOL_FAILURE,
            "runtime control failed",
        )
    print(f"session={reply.session}")
    print("runtime=stopped")
    return RuntimeCliExitCode.SUCCESS


def _runtime_runs_list(*, limit: int, as_json: bool) -> int:
    try:
        records = list_runs(limit=limit)
    except HistoryError:
        return _runtime_failure(
            RuntimeCliExitCode.HISTORY_STORE_FAILURE,
            "runtime history failed",
        )
    if as_json:
        print(
            json.dumps(
                {"run_count": len(records), "runs": [_run_document(run) for run in records]},
                ensure_ascii=True,
                separators=(",", ":"),
                sort_keys=True,
            )
        )
        return RuntimeCliExitCode.SUCCESS
    print(f"run-count={len(records)}")
    for record in records:
        print(
            f"run={record.run_id} session={record.session_id} "
            f"result={record.result.value if record.result is not None else 'incomplete'} "
            f"started-at={record.started_at} ended-at={record.ended_at or 'none'} "
            "event-high-water-mark="
            + (
                str(record.event_high_water_mark)
                if record.event_high_water_mark is not None
                else "none"
            )
        )
    return RuntimeCliExitCode.SUCCESS


def _runtime_runs_show(run_id: str, *, as_json: bool) -> int:
    try:
        record = get_run(run_id)
    except (InvalidRunIdError, RunNotFoundError):
        return _runtime_failure(
            RuntimeCliExitCode.RUN_NOT_FOUND,
            "runtime run is not found",
        )
    except HistoryError:
        return _runtime_failure(
            RuntimeCliExitCode.HISTORY_STORE_FAILURE,
            "runtime history failed",
        )
    if as_json:
        print(
            json.dumps(
                _run_document(record),
                ensure_ascii=True,
                separators=(",", ":"),
                sort_keys=True,
            )
        )
    else:
        for line in _render_run(record):
            print(line)
    return RuntimeCliExitCode.SUCCESS


def _runtime_runs_prune(*, keep: int) -> int:
    try:
        deleted = prune_runs(keep=keep)
    except HistoryError:
        return _runtime_failure(
            RuntimeCliExitCode.HISTORY_STORE_FAILURE,
            "runtime history failed",
        )
    print(f"deleted-runs={deleted}")
    return RuntimeCliExitCode.SUCCESS


def _runtime_events(
    run_id: str,
    *,
    after: int,
    limit: int,
    as_json: bool,
) -> int:
    try:
        records = list_events(run_id, after=after, limit=limit)
    except (InvalidRunIdError, RunNotFoundError):
        return _runtime_failure(
            RuntimeCliExitCode.RUN_NOT_FOUND,
            "runtime run is not found",
        )
    except HistoryError:
        return _runtime_failure(
            RuntimeCliExitCode.HISTORY_STORE_FAILURE,
            "runtime history failed",
        )
    if as_json:
        print(
            json.dumps(
                {
                    "event_count": len(records),
                    "events": [_event_document(event) for event in records],
                    "run_id": run_id,
                },
                ensure_ascii=True,
                separators=(",", ":"),
                sort_keys=True,
            )
        )
        return RuntimeCliExitCode.SUCCESS
    print(f"run={run_id}")
    print(f"event-count={len(records)}")
    for record in records:
        print(_render_event(record))
    return RuntimeCliExitCode.SUCCESS


def _render_run(record: RunRecord) -> tuple[str, ...]:
    return (
        f"schema-version={record.schema_version}",
        f"run={record.run_id}",
        f"session={record.session_id}",
        f"config-fingerprint={record.config_fingerprint}",
        f"package-version={record.package_version}",
        f"platform={record.platform}",
        f"started-at={record.started_at}",
        f"ended-at={record.ended_at or 'none'}",
        f"result={record.result.value if record.result is not None else 'incomplete'}",
        f"stop-reason={record.stop_reason.value if record.stop_reason is not None else 'none'}",
        "event-high-water-mark="
        f"{record.event_high_water_mark if record.event_high_water_mark is not None else 'none'}",
    )


def _run_document(record: RunRecord) -> dict[str, object]:
    return {
        "config_fingerprint": record.config_fingerprint,
        "ended_at": record.ended_at,
        "event_high_water_mark": record.event_high_water_mark,
        "package_version": record.package_version,
        "platform": record.platform,
        "result": record.result.value if record.result is not None else None,
        "run_id": record.run_id,
        "schema_version": record.schema_version,
        "session_id": record.session_id,
        "started_at": record.started_at,
        "stop_reason": record.stop_reason.value if record.stop_reason is not None else None,
    }


def _render_event(record: EventRecord) -> str:
    return (
        f"event={record.sequence} type={record.event_type.value} "
        f"outcome={record.outcome.value} severity={record.severity} "
        "resource="
        f"{record.resource_identity.value if record.resource_identity is not None else 'none'} "
        "lifecycle="
        f"{record.lifecycle_state.value if record.lifecycle_state is not None else 'none'} "
        "health="
        f"{record.health_status.value if record.health_status is not None else 'none'} "
        f"recorded-at={record.recorded_at} summary={record.summary}"
    )


def _event_document(record: EventRecord) -> dict[str, object]:
    return {
        "event_type": record.event_type.value,
        "health_status": (
            None if record.health_status is None else record.health_status.value
        ),
        "lifecycle_state": (
            None if record.lifecycle_state is None else record.lifecycle_state.value
        ),
        "outcome": record.outcome.value,
        "recorded_at": record.recorded_at,
        "resource_identity": (
            None if record.resource_identity is None else record.resource_identity.value
        ),
        "run_id": record.run_id,
        "schema_version": record.schema_version,
        "sequence": record.sequence,
        "severity": record.severity,
        "summary": record.summary,
    }


def _history_limit(value: str) -> int:
    try:
        return validate_limit(int(value))
    except (ValueError, InvalidHistoryLimitError) as error:
        raise argparse.ArgumentTypeError("limit must be between 1 and 100") from error


def _event_after(value: str) -> int:
    try:
        return validate_event_cursor(int(value))
    except (ValueError, InvalidEventCursorError) as error:
        raise argparse.ArgumentTypeError("after must be an integer at or above -1") from error


def _event_limit(value: str) -> int:
    try:
        return validate_event_limit(int(value))
    except (ValueError, InvalidEventLimitError) as error:
        raise argparse.ArgumentTypeError("limit must be between 1 and 1000") from error


def _retention_keep(value: str) -> int:
    try:
        return validate_retention_keep(int(value))
    except (ValueError, InvalidRetentionKeepError) as error:
        raise argparse.ArgumentTypeError(
            "keep must be between 0 and 9223372036854775807"
        ) from error


def _print_runtime_ready(session: str) -> None:
    print(f"session={session}", flush=True)
    print("runtime=running", flush=True)
    print("control=ready", flush=True)


def _runtime_failure(code: RuntimeCliExitCode, message: str) -> int:
    print(f"error: {message}", file=sys.stderr)
    return code


def _validate_config(path: Path) -> int:
    try:
        load_config(path)
    except ConfigurationError:
        print("error: configuration is invalid", file=sys.stderr)
        return FAILURE
    print("configuration=valid")
    return SUCCESS


def _scaffold_motor_driver(
    output: Path,
    *,
    package_name: str,
    model_name: str,
) -> int:
    try:
        created = create_motor_driver_scaffold(
            output,
            package_name=package_name,
            model_name=model_name,
        )
    except (MotorDriverScaffoldError, OSError):
        print("error: motor-driver scaffold failed", file=sys.stderr)
        return FAILURE
    print("scaffold=motor-driver")
    print(f"package={package_name}")
    print(f"model={model_name}")
    print(f"files={len(created)}")
    return SUCCESS


def _hardware_preflight(
    path: Path,
    *,
    physical_operation_consent: str | None,
) -> int:
    """Print a deterministic plan without constructing a motor or transport."""
    try:
        config = load_hardware_acceptance_config(path)
        registry = ModelRegistry()
        register_dynamixel_xl430_motor(registry)
        plan = preflight_hardware_acceptance(
            config,
            registry,
            XL430_W250_T_ACCEPTANCE_PROFILE,
            physical_operation_consent=physical_operation_consent,
        )
    except HardwareAcceptanceError:
        print("error: hardware acceptance preflight failed", file=sys.stderr)
        return FAILURE
    for line in plan.evidence_lines():
        print(line)
    return SUCCESS


async def run_sim_motor_demo() -> tuple[str, ...]:
    """Run the deterministic loopback simulation workflow and return its transcript."""
    config = _load_demo_config()
    registry = ModelRegistry()
    register_simulated_motor(registry)
    runtime = RuntimeManager(config, registry)
    server = MotorGrpcServer(runtime, port=0)
    channel: grpc.aio.Channel | None = None
    transcript = ["demo=sim-motor", "configuration=valid"]
    primary_failure: BaseException | None = None
    cleanup_failures: list[BaseException] = []

    try:
        await runtime.start()
        transcript.append("runtime=running")
        await server.start_transport()
        transcript.append("grpc=running")
        channel = grpc.aio.insecure_channel(server.target)
        client = motor_pb2_grpc.MotorServiceStub(channel)

        listing = await client.ListMotors(motor_pb2.ListMotorsRequest())
        identities = tuple(motor.identity for motor in listing.motors)
        if identities != (_DEMO_IDENTITY.value,):
            raise RuntimeError("demo runtime did not expose the expected motor")
        transcript.append(f"motors={','.join(identities)}")

        motor = runtime.get_resource(_DEMO_IDENTITY)
        if not isinstance(motor, SimulatedMotor):
            raise RuntimeError("demo resource is not a simulated motor")

        await client.ApplyMotorCommand(
            motor_pb2.ApplyMotorCommandRequest(
                identity=_DEMO_IDENTITY.value,
                angular_velocity_radians_per_second=_POSITIVE_VELOCITY,
            )
        )
        transcript.append(f"command=positive velocity={_POSITIVE_VELOCITY:.3f}")
        motor.advance_time(_POSITIVE_TIME_STEP)
        transcript.append(f"advance={_POSITIVE_TIME_STEP:.3f}")
        positive = await client.GetMotorState(
            motor_pb2.GetMotorStateRequest(identity=_DEMO_IDENTITY.value)
        )
        transcript.append(_state_line("positive", positive.state))

        await client.ApplyMotorCommand(
            motor_pb2.ApplyMotorCommandRequest(
                identity=_DEMO_IDENTITY.value,
                angular_velocity_radians_per_second=_NEGATIVE_VELOCITY,
            )
        )
        transcript.append(f"command=negative velocity={_NEGATIVE_VELOCITY:.3f}")
        motor.advance_time(_NEGATIVE_TIME_STEP)
        transcript.append(f"advance={_NEGATIVE_TIME_STEP:.3f}")
        negative = await client.GetMotorState(
            motor_pb2.GetMotorStateRequest(identity=_DEMO_IDENTITY.value)
        )
        transcript.append(_state_line("negative", negative.state))

        zero = await client.ApplyMotorCommand(
            motor_pb2.ApplyMotorCommandRequest(
                identity=_DEMO_IDENTITY.value,
                angular_velocity_radians_per_second=0.0,
            )
        )
        transcript.append(
            f"command=zero velocity={zero.state.angular_velocity_radians_per_second:.3f}"
        )
        stopped = await client.StopMotor(
            motor_pb2.StopMotorRequest(identity=_DEMO_IDENTITY.value)
        )
        transcript.append(
            f"stop velocity={stopped.state.angular_velocity_radians_per_second:.3f}"
        )
    except BaseException as error:
        primary_failure = error
    finally:
        if channel is not None:
            try:
                await channel.close()
            except BaseException as error:
                cleanup_failures.append(error)
        if server.state is RpcTransportState.RUNNING:
            try:
                await server.stop_transport()
            except BaseException as error:
                cleanup_failures.append(error)
        if runtime.state is RuntimeManagerState.RUNNING:
            try:
                await runtime.shutdown()
            except BaseException as error:
                cleanup_failures.append(error)

    if primary_failure is not None:
        raise primary_failure
    if cleanup_failures:
        raise cleanup_failures[0]
    transcript.append("cleanup grpc=stopped runtime=stopped")
    return tuple(transcript)


def _load_demo_config() -> RuntimeConfig:
    repository_config = Path(__file__).parents[2] / "examples/configs/sim-motor.yaml"
    if repository_config.is_file():
        return load_config(repository_config)
    packaged_config = files("hiyelx").joinpath("examples/configs/sim-motor.yaml")
    with as_file(packaged_config) as config_path:
        return load_config(config_path)


def _state_line(label: str, state: motor_pb2.MotorState) -> str:
    return (
        f"state={label} position={state.angular_position_radians:.3f} "
        f"velocity={state.angular_velocity_radians_per_second:.3f}"
    )


if __name__ == "__main__":
    raise SystemExit(main())
