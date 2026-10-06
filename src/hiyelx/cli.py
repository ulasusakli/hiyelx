"""Command-line workflows for local HIYELX development."""

from __future__ import annotations

import argparse
import asyncio
import sys
from collections.abc import Sequence
from importlib.resources import as_file, files
from pathlib import Path

import grpc

from hiyelx.config import ConfigurationError, RuntimeConfig, load_config
from hiyelx.models import ModelRegistry
from hiyelx.resources import ResourceIdentity
from hiyelx.rpc import MotorGrpcServer, RpcTransportState
from hiyelx.rpc.generated import motor_pb2, motor_pb2_grpc
from hiyelx.runtime import RuntimeManager, RuntimeManagerState
from hiyelx.simulation import SimulatedMotor, register_simulated_motor

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
    return parser


def _validate_config(path: Path) -> int:
    try:
        load_config(path)
    except ConfigurationError:
        print("error: configuration is invalid", file=sys.stderr)
        return FAILURE
    print("configuration=valid")
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
