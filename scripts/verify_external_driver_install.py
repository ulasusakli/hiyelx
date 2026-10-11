"""Verify an external driver wheel against a clean installed HIYELX wheel."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

SUCCESS = 0
FAILURE = 1
ENVIRONMENT_BLOCKED = 2

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
PACKAGE_NAME = "acme_motor_driver"
MODEL_NAME = "motor.acme.reference"
EXPECTED_SCAFFOLD_FILES = (
    Path("README.md"),
    Path("acme_motor_driver/__init__.py"),
    Path("acme_motor_driver/acme_motor_driver.py"),
    Path("pyproject.toml"),
    Path("runtime.yaml"),
    Path("tests/test_driver.py"),
)
EXPECTED_TRANSCRIPT = (
    "configuration=valid",
    "imports=clean",
    "runtime=running",
    "grpc=running",
    "motors=example_motor",
    "state=initial position=0.000 velocity=0.000",
    "command velocity=0.250",
    "stop velocity=0.000",
    "cleanup-order=command:0.0,shutdown",
    "cleanup grpc=stopped runtime=stopped",
)


class ExternalDriverVerificationError(Exception):
    """Base class for sanitized external-driver verification failures."""


class ExternalDriverVerificationFailure(ExternalDriverVerificationError):
    """The external-driver evidence did not satisfy its contract."""


class ExternalDriverEnvironmentBlocked(ExternalDriverVerificationError):
    """The host prevented build, package installation, or loopback execution."""


@dataclass(frozen=True, slots=True)
class CommandResult:
    """Captured subprocess output for the real and injected command runners."""

    returncode: int
    stdout: bytes
    stderr: bytes


@dataclass(frozen=True, slots=True)
class ExternalDriverVerificationReport:
    """Stable evidence returned by the isolated verifier."""

    hiyelx_wheel: str
    external_wheel: str
    transcript: tuple[str, ...]


CommandRunner = Callable[[Sequence[str], Path, Mapping[str, str]], CommandResult]


def main() -> int:
    """Run the external-driver gate with concise sanitized output."""
    try:
        report = run_external_driver_verification()
    except ExternalDriverEnvironmentBlocked:
        print(
            "blocked: external-driver verification requires package access "
            "and loopback support",
            file=sys.stderr,
        )
        return ENVIRONMENT_BLOCKED
    except Exception:
        print("error: external-driver verification failed", file=sys.stderr)
        return FAILURE
    print(f"hiyelx-wheel={report.hiyelx_wheel}")
    print(f"external-wheel={report.external_wheel}")
    print("scaffold-tests=passed")
    print("imports=clean")
    print("external-runtime-grpc=passed")
    return SUCCESS


def run_external_driver_verification(
    *,
    repository_root: Path = REPOSITORY_ROOT,
    runner: CommandRunner | None = None,
    temporary_parent: Path | None = None,
) -> ExternalDriverVerificationReport:
    """Build, install, and execute one generated driver outside source trees."""
    command_runner = runner or _run_command
    uv = shutil.which("uv")
    if uv is None:
        raise ExternalDriverEnvironmentBlocked

    with tempfile.TemporaryDirectory(
        prefix="hiyelx-external-driver-",
        dir=temporary_parent,
    ) as temporary_name:
        workspace = Path(temporary_name)
        hiyelx_dist = workspace / "hiyelx-wheel"
        environment_path = workspace / "venv"
        driver_source = workspace / "driver-source"
        driver_dist = workspace / "driver-wheel"
        application = workspace / "application"
        environment = _isolated_environment()

        _require_success(
            command_runner(
                (
                    uv,
                    "build",
                    "--wheel",
                    "--no-create-gitignore",
                    "--out-dir",
                    str(hiyelx_dist),
                    str(repository_root),
                ),
                workspace,
                environment,
            ),
            environment_sensitive=True,
        )
        hiyelx_wheel = require_single_wheel(hiyelx_dist, "hiyelx-*.whl")

        _require_success(
            command_runner(
                (uv, "venv", "--python", "3.12", "--no-project", str(environment_path)),
                workspace,
                environment,
            ),
            environment_sensitive=True,
        )
        python, executable = _environment_commands(environment_path)
        version = _require_success(
            command_runner((str(python), "--version"), workspace, environment),
            environment_sensitive=True,
        )
        if not (version.stdout + version.stderr).startswith(b"Python 3.12."):
            raise ExternalDriverVerificationFailure

        _require_success(
            command_runner(
                (
                    uv,
                    "pip",
                    "install",
                    "--strict",
                    "--python",
                    str(python),
                    str(hiyelx_wheel),
                ),
                workspace,
                environment,
            ),
            environment_sensitive=True,
        )
        _require_success(
            command_runner(
                (
                    uv,
                    "pip",
                    "install",
                    "--strict",
                    "--python",
                    str(python),
                    "pytest==9.1.1",
                    "pytest-asyncio==1.4.0",
                ),
                workspace,
                environment,
            ),
            environment_sensitive=True,
        )

        scaffolded = _require_success(
            command_runner(
                (
                    str(executable),
                    "scaffold",
                    "motor-driver",
                    str(driver_source),
                    "--package-name",
                    PACKAGE_NAME,
                    "--model-name",
                    MODEL_NAME,
                ),
                workspace,
                environment,
            ),
            environment_sensitive=False,
        )
        if _strip_one_final_newline(scaffolded.stdout) != (
            b"scaffold=motor-driver\n"
            b"package=acme_motor_driver\n"
            b"model=motor.acme.reference\n"
            b"files=6"
        ):
            raise ExternalDriverVerificationFailure
        assert_scaffold_layout(driver_source)

        _require_success(
            command_runner(
                (str(python), "-m", "pytest", "-q"),
                driver_source,
                environment,
            ),
            environment_sensitive=False,
        )
        _require_success(
            command_runner(
                (
                    uv,
                    "build",
                    "--wheel",
                    "--no-create-gitignore",
                    "--out-dir",
                    str(driver_dist),
                    str(driver_source),
                ),
                workspace,
                environment,
            ),
            environment_sensitive=True,
        )
        external_wheel = require_single_wheel(
            driver_dist,
            "acme_motor_driver-*.whl",
        )
        _require_success(
            command_runner(
                (
                    uv,
                    "pip",
                    "install",
                    "--strict",
                    "--python",
                    str(python),
                    "--no-index",
                    str(external_wheel),
                ),
                workspace,
                environment,
            ),
            environment_sensitive=True,
        )

        application.mkdir()
        imported = _require_success(
            command_runner(
                (
                    str(python),
                    "-c",
                    "from pathlib import Path; import hiyelx, acme_motor_driver; "
                    "print(Path(hiyelx.__file__).resolve()); "
                    "print(Path(acme_motor_driver.__file__).resolve())",
                ),
                application,
                environment,
            ),
            environment_sensitive=False,
        )
        paths = imported.stdout.decode("utf-8").splitlines()
        if len(paths) != 2:
            raise ExternalDriverVerificationFailure
        assert_installed_package_path(
            paths[0],
            environment_path=environment_path,
            forbidden_roots=(repository_root, driver_source),
        )
        assert_installed_package_path(
            paths[1],
            environment_path=environment_path,
            forbidden_roots=(repository_root, driver_source),
        )

        application_path = application / "verify_external_driver.py"
        application_path.write_text(_EXTERNAL_APPLICATION, encoding="utf-8")
        executed = _require_success(
            command_runner(
                (
                    str(python),
                    str(application_path),
                    str(driver_source / "runtime.yaml"),
                ),
                application,
                environment,
            ),
            environment_sensitive=True,
        )
        transcript = tuple(
            _strip_one_final_newline(executed.stdout).decode("utf-8").splitlines()
        )
        assert_transcript(transcript)
        return ExternalDriverVerificationReport(
            hiyelx_wheel=hiyelx_wheel.name,
            external_wheel=external_wheel.name,
            transcript=transcript,
        )


def require_single_wheel(directory: Path, pattern: str) -> Path:
    """Return exactly one matching wheel."""
    wheels = tuple(directory.glob(pattern))
    if len(wheels) != 1:
        raise ExternalDriverVerificationFailure
    return wheels[0]


def assert_scaffold_layout(scaffold_path: Path) -> None:
    """Require the bounded six-file scaffold before build artifacts exist."""
    if not scaffold_path.is_dir():
        raise ExternalDriverVerificationFailure
    actual = tuple(
        sorted(
            path.relative_to(scaffold_path)
            for path in scaffold_path.rglob("*")
            if path.is_file()
        )
    )
    if actual != EXPECTED_SCAFFOLD_FILES:
        raise ExternalDriverVerificationFailure


def assert_installed_package_path(
    imported_path: str,
    *,
    environment_path: Path,
    forbidden_roots: Sequence[Path],
) -> None:
    """Require an import from the clean environment and outside source roots."""
    resolved = Path(imported_path).resolve()
    environment = environment_path.resolve()
    if resolved != environment and environment not in resolved.parents:
        raise ExternalDriverVerificationFailure
    for root in forbidden_roots:
        source = root.resolve()
        if resolved == source or source in resolved.parents:
            raise ExternalDriverVerificationFailure


def assert_transcript(transcript: tuple[str, ...]) -> None:
    """Require the stable external Runtime/gRPC evidence transcript."""
    if transcript != EXPECTED_TRANSCRIPT:
        raise ExternalDriverVerificationFailure


def _run_command(
    command: Sequence[str],
    cwd: Path,
    environment: Mapping[str, str],
) -> CommandResult:
    try:
        completed = subprocess.run(
            command,
            cwd=cwd,
            env=environment,
            capture_output=True,
            check=False,
            timeout=180,
        )
    except subprocess.TimeoutExpired as error:
        raise ExternalDriverEnvironmentBlocked from error
    return CommandResult(completed.returncode, completed.stdout, completed.stderr)


def _require_success(
    result: CommandResult,
    *,
    environment_sensitive: bool,
) -> CommandResult:
    if result.returncode == SUCCESS:
        return result
    if environment_sensitive and _looks_environment_blocked(result.stderr):
        raise ExternalDriverEnvironmentBlocked
    raise ExternalDriverVerificationFailure


def _looks_environment_blocked(stderr: bytes) -> bool:
    lowered = stderr.lower()
    indicators = (
        b"network",
        b"connection",
        b"dns",
        b"resolve",
        b"timed out",
        b"operation not permitted",
        b"permission denied",
        b"failed to bind",
        b"python 3.12",
    )
    return any(indicator in lowered for indicator in indicators)


def _isolated_environment() -> dict[str, str]:
    environment = dict(os.environ)
    for name in (
        "PYTHONPATH",
        "PYTHONHOME",
        "VIRTUAL_ENV",
        "UV_PROJECT_ENVIRONMENT",
    ):
        environment.pop(name, None)
    environment["PYTHONNOUSERSITE"] = "1"
    return environment


def _environment_commands(environment_path: Path) -> tuple[Path, Path]:
    if os.name == "nt":
        scripts = environment_path / "Scripts"
        return scripts / "python.exe", scripts / "hiyelx.exe"
    binaries = environment_path / "bin"
    return binaries / "python", binaries / "hiyelx"


def _strip_one_final_newline(value: bytes) -> bytes:
    return value[:-1] if value.endswith(b"\n") else value


_EXTERNAL_APPLICATION = '''from __future__ import annotations

import asyncio
import sys

import grpc

from acme_motor_driver import register_acme_motor_driver
from hiyelx.config import load_config
from hiyelx.models import ModelRegistry
from hiyelx.resources import ResourceIdentity
from hiyelx.rpc import MotorGrpcServer, RpcTransportState
from hiyelx.rpc.generated import motor_pb2, motor_pb2_grpc
from hiyelx.runtime import RuntimeManager, RuntimeManagerState


async def run() -> tuple[str, ...]:
    registry = ModelRegistry()
    register_acme_motor_driver(registry)
    runtime = RuntimeManager(load_config(sys.argv[1]), registry)
    server = MotorGrpcServer(runtime, port=0)
    channel: grpc.aio.Channel | None = None
    transcript = ["configuration=valid", "imports=clean"]
    motor = runtime.get_resource(ResourceIdentity("example_motor"))
    try:
        await runtime.start()
        transcript.append("runtime=running")
        await server.start_transport()
        transcript.append("grpc=running")
        channel = grpc.aio.insecure_channel(server.target)
        client = motor_pb2_grpc.MotorServiceStub(channel)

        listing = await client.ListMotors(motor_pb2.ListMotorsRequest())
        identities = tuple(item.identity for item in listing.motors)
        if identities != ("example_motor",):
            raise RuntimeError
        transcript.append("motors=example_motor")

        initial = await client.GetMotorState(
            motor_pb2.GetMotorStateRequest(identity="example_motor")
        )
        transcript.append(
            "state=initial "
            f"position={initial.state.angular_position_radians:.3f} "
            f"velocity={initial.state.angular_velocity_radians_per_second:.3f}"
        )
        commanded = await client.ApplyMotorCommand(
            motor_pb2.ApplyMotorCommandRequest(
                identity="example_motor",
                angular_velocity_radians_per_second=0.25,
            )
        )
        transcript.append(
            f"command velocity={commanded.state.angular_velocity_radians_per_second:.3f}"
        )
        stopped = await client.StopMotor(
            motor_pb2.StopMotorRequest(identity="example_motor")
        )
        transcript.append(
            f"stop velocity={stopped.state.angular_velocity_radians_per_second:.3f}"
        )
    finally:
        if channel is not None:
            await channel.close()
        if server.state is RpcTransportState.RUNNING:
            await server.stop_transport()
        if runtime.state is RuntimeManagerState.RUNNING:
            await runtime.shutdown()

    events = getattr(motor, "events")
    if events[-2:] != ("command:0.0", "shutdown"):
        raise RuntimeError
    transcript.append("cleanup-order=command:0.0,shutdown")
    if server.state is not RpcTransportState.STOPPED:
        raise RuntimeError
    if runtime.state is not RuntimeManagerState.STOPPED:
        raise RuntimeError
    transcript.append("cleanup grpc=stopped runtime=stopped")
    return tuple(transcript)


for line in asyncio.run(run()):
    print(line)
'''


if __name__ == "__main__":
    raise SystemExit(main())
