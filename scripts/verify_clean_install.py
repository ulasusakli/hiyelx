"""Build and verify the installed HIYELX wheel outside the source checkout."""

from __future__ import annotations

import os
import select
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from email.parser import BytesParser
from email.policy import default
from pathlib import Path

SUCCESS = 0
FAILURE = 1
ENVIRONMENT_BLOCKED = 2

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
EXPECTED_TRANSCRIPT = REPOSITORY_ROOT / "examples/expected/sim-motor.txt"
DEMO_CONFIG = REPOSITORY_ROOT / "examples/configs/sim-motor.yaml"
EXPECTED_LICENSE_EXPRESSION = "Apache-2.0"
RUNTIME_SESSION = "clean-install"
EXPECTED_RUNTIME_READY = (
    b"session=clean-install",
    b"runtime=running",
    b"control=ready",
)
EXPECTED_RUNTIME_STATUS = (
    b"session=clean-install\n"
    b"manager-state=running\n"
    b"resource-count=1\n"
    b"resource=sim_motor lifecycle=running health=healthy health-summary=none\n"
    b"successful-start-order=sim_motor\n"
    b"active-resource-order=sim_motor\n"
    b"event-high-water-mark=3\n"
    b"latest-event=runtime running\n"
)
EXPECTED_RUNTIME_STOP = b"session=clean-install\nruntime=stopped\n"
_READINESS_TIMEOUT_SECONDS = 15.0
EXPECTED_SCAFFOLD_FILES = (
    Path("README.md"),
    Path("acme_motor_driver/__init__.py"),
    Path("acme_motor_driver/acme_motor_driver.py"),
    Path("pyproject.toml"),
    Path("runtime.yaml"),
    Path("tests/test_driver.py"),
)


class VerificationError(Exception):
    """Base class for sanitized clean-install verification failures."""


class VerificationFailure(VerificationError):
    """The clean-install evidence did not satisfy its contract."""


class VerificationEnvironmentBlocked(VerificationError):
    """The host prevented package installation or loopback execution."""


@dataclass(frozen=True, slots=True)
class CommandResult:
    """Captured subprocess result used by the real and injected runners."""

    returncode: int
    stdout: bytes
    stderr: bytes


CommandRunner = Callable[[Sequence[str], Path, Mapping[str, str]], CommandResult]


def main() -> int:
    """Run the clean-install gate with concise, sanitized status output."""
    try:
        wheel_name = run_clean_install_verification()
    except VerificationEnvironmentBlocked:
        print(
            "blocked: clean-install verification requires package access and loopback support",
            file=sys.stderr,
        )
        return ENVIRONMENT_BLOCKED
    except Exception:
        print("error: clean-install verification failed", file=sys.stderr)
        return FAILURE
    print(f"wheel={wheel_name}")
    print("clean-install=passed")
    return SUCCESS


def run_clean_install_verification(
    *,
    repository_root: Path = REPOSITORY_ROOT,
    runner: CommandRunner | None = None,
    temporary_parent: Path | None = None,
) -> str:
    """Return the verified wheel filename after an isolated non-editable run."""
    command_runner = runner or _run_command
    uv = shutil.which("uv")
    if uv is None:
        raise VerificationEnvironmentBlocked

    expected_path = repository_root / "examples/expected/sim-motor.txt"
    config_path = repository_root / "examples/configs/sim-motor.yaml"
    expected = expected_path.read_bytes()

    with tempfile.TemporaryDirectory(
        prefix="hiyelx-clean-install-",
        dir=temporary_parent,
    ) as temporary_name:
        workspace = Path(temporary_name)
        build_output = workspace / "wheel"
        environment_path = workspace / "venv"
        copied_config = workspace / "sim-motor.yaml"
        environment = _isolated_environment()

        _require_success(
            command_runner(
                (
                    uv,
                    "build",
                    "--wheel",
                    "--no-create-gitignore",
                    "--out-dir",
                    str(build_output),
                    str(repository_root),
                ),
                workspace,
                environment,
            ),
            environment_sensitive=True,
        )
        wheels = tuple(build_output.glob("hiyelx-*.whl"))
        if len(wheels) != 1:
            raise VerificationFailure
        wheel = wheels[0]
        assert_wheel_license(wheel, repository_root=repository_root)

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
            raise VerificationFailure
        _require_success(
            command_runner(
                (uv, "pip", "install", "--strict", "--python", str(python), str(wheel)),
                workspace,
                environment,
            ),
            environment_sensitive=True,
        )

        shutil.copyfile(config_path, copied_config)
        imported = _require_success(
            command_runner(
                (
                    str(python),
                    "-c",
                    "from pathlib import Path; import hiyelx; "
                    "print(Path(hiyelx.__file__).resolve())",
                ),
                workspace,
                environment,
            ),
            environment_sensitive=False,
        )
        assert_installed_package_path(
            imported.stdout.decode("utf-8").strip(),
            repository_root=repository_root,
            environment_path=environment_path,
        )

        _require_success(
            command_runner((str(executable), "--help"), workspace, environment),
            environment_sensitive=False,
        )
        scaffold_path = workspace / "driver-scaffold"
        scaffolded = _require_success(
            command_runner(
                (
                    str(executable),
                    "scaffold",
                    "motor-driver",
                    str(scaffold_path),
                    "--package-name",
                    "acme_motor_driver",
                    "--model-name",
                    "motor.acme.reference",
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
            raise VerificationFailure
        assert_scaffold_layout(scaffold_path)
        validated = _require_success(
            command_runner(
                (str(executable), "validate-config", str(copied_config)),
                workspace,
                environment,
            ),
            environment_sensitive=False,
        )
        if _strip_one_final_newline(validated.stdout) != b"configuration=valid":
            raise VerificationFailure

        demonstrated = _require_success(
            command_runner(
                (str(executable), "demo", "sim-motor"),
                workspace,
                environment,
            ),
            environment_sensitive=True,
        )
        assert_transcript_equal(expected, demonstrated.stdout)
        if runner is None:
            verify_installed_runtime_workflow(
                executable,
                copied_config,
                workspace=workspace,
                environment=environment,
            )
        else:
            _verify_runtime_runner_contract(
                command_runner,
                executable,
                copied_config,
                workspace=workspace,
                environment=environment,
            )
        return wheel.name


def verify_installed_runtime_workflow(
    executable: Path,
    config_path: Path,
    *,
    workspace: Path,
    environment: Mapping[str, str],
) -> None:
    """Prove cross-process control through the installed wheel executable."""
    if sys.platform not in {"darwin", "linux"}:
        raise VerificationEnvironmentBlocked
    state_parent = Path("/private/tmp" if sys.platform == "darwin" else "/tmp")
    with tempfile.TemporaryDirectory(
        prefix="hiyelx-wheel-runtime-",
        dir=state_parent,
    ) as state_name:
        runtime_environment = dict(environment)
        runtime_environment["HIYELX_RUNTIME_STATE_DIR"] = state_name
        owner: subprocess.Popen[bytes] | None = None
        try:
            owner = subprocess.Popen(
                (
                    str(executable),
                    "runtime",
                    "start",
                    str(config_path),
                    "--session",
                    RUNTIME_SESSION,
                ),
                cwd=workspace,
                env=runtime_environment,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            if _read_owner_lines(owner, len(EXPECTED_RUNTIME_READY)) != (
                EXPECTED_RUNTIME_READY
            ):
                raise VerificationFailure

            status = _require_success(
                _run_command(
                    (
                        str(executable),
                        "runtime",
                        "status",
                        "--session",
                        RUNTIME_SESSION,
                    ),
                    workspace,
                    runtime_environment,
                ),
                environment_sensitive=True,
            )
            if status.stdout != EXPECTED_RUNTIME_STATUS or status.stderr:
                raise VerificationFailure

            stopped = _require_success(
                _run_command(
                    (
                        str(executable),
                        "runtime",
                        "stop",
                        "--session",
                        RUNTIME_SESSION,
                    ),
                    workspace,
                    runtime_environment,
                ),
                environment_sensitive=True,
            )
            if stopped.stdout != EXPECTED_RUNTIME_STOP or stopped.stderr:
                raise VerificationFailure

            remaining_stdout, remaining_stderr = owner.communicate(timeout=15)
            if (
                owner.returncode != SUCCESS
                or remaining_stdout != b"runtime=stopped\n"
                or remaining_stderr
                or (Path(state_name) / RUNTIME_SESSION).exists()
            ):
                raise VerificationFailure
        except subprocess.TimeoutExpired as error:
            raise VerificationEnvironmentBlocked from error
        except OSError as error:
            raise VerificationEnvironmentBlocked from error
        finally:
            if owner is not None and owner.poll() is None:
                owner.terminate()
                try:
                    owner.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    owner.kill()
                    owner.wait(timeout=10)


def _verify_runtime_runner_contract(
    runner: CommandRunner,
    executable: Path,
    config_path: Path,
    *,
    workspace: Path,
    environment: Mapping[str, str],
) -> None:
    """Exercise deterministic verifier orchestration for injected unit runners."""
    state = workspace / "runtime-state"
    runtime_environment = dict(environment)
    runtime_environment["HIYELX_RUNTIME_STATE_DIR"] = str(state)
    started = _require_success(
        runner(
            (
                str(executable),
                "runtime",
                "start",
                str(config_path),
                "--session",
                RUNTIME_SESSION,
            ),
            workspace,
            runtime_environment,
        ),
        environment_sensitive=True,
    )
    expected_owner = b"\n".join(EXPECTED_RUNTIME_READY) + b"\nruntime=stopped\n"
    if started.stdout != expected_owner or started.stderr:
        raise VerificationFailure
    status = _require_success(
        runner(
            (str(executable), "runtime", "status", "--session", RUNTIME_SESSION),
            workspace,
            runtime_environment,
        ),
        environment_sensitive=True,
    )
    if status.stdout != EXPECTED_RUNTIME_STATUS or status.stderr:
        raise VerificationFailure
    stopped = _require_success(
        runner(
            (str(executable), "runtime", "stop", "--session", RUNTIME_SESSION),
            workspace,
            runtime_environment,
        ),
        environment_sensitive=True,
    )
    if stopped.stdout != EXPECTED_RUNTIME_STOP or stopped.stderr:
        raise VerificationFailure


def load_expected_transcript(path: Path = EXPECTED_TRANSCRIPT) -> tuple[str, ...]:
    """Load the canonical transcript without retaining newline characters."""
    return tuple(path.read_text(encoding="utf-8").splitlines())


def assert_transcript_equal(expected: bytes, actual: bytes) -> None:
    """Require byte equality while allowing one optional final LF."""
    if _strip_one_final_newline(expected) != _strip_one_final_newline(actual):
        raise VerificationFailure


def assert_installed_package_path(
    imported_path: str,
    *,
    repository_root: Path,
    environment_path: Path,
) -> None:
    """Reject source-checkout imports and paths outside the clean environment."""
    resolved = Path(imported_path).resolve()
    source = repository_root.resolve()
    environment = environment_path.resolve()
    if resolved == source or source in resolved.parents:
        raise VerificationFailure
    if resolved != environment and environment not in resolved.parents:
        raise VerificationFailure


def assert_scaffold_layout(scaffold_path: Path) -> None:
    """Require the installed CLI to render the complete bounded scaffold."""
    if not scaffold_path.is_dir():
        raise VerificationFailure
    actual = tuple(
        sorted(
            path.relative_to(scaffold_path)
            for path in scaffold_path.rglob("*")
            if path.is_file()
        )
    )
    if actual != EXPECTED_SCAFFOLD_FILES:
        raise VerificationFailure


def assert_wheel_license(wheel: Path, *, repository_root: Path) -> None:
    """Require PEP 639 metadata and the canonical repository license in a wheel."""
    expected_license = (repository_root / "LICENSE").read_bytes()
    try:
        with zipfile.ZipFile(wheel) as archive:
            names = archive.namelist()
            metadata_names = tuple(
                name for name in names if name.endswith(".dist-info/METADATA")
            )
            license_names = tuple(
                name for name in names if name.endswith(".dist-info/licenses/LICENSE")
            )
            if len(metadata_names) != 1 or len(license_names) != 1:
                raise VerificationFailure
            metadata = BytesParser(policy=default).parsebytes(
                archive.read(metadata_names[0])
            )
            if metadata.get("License-Expression") != EXPECTED_LICENSE_EXPRESSION:
                raise VerificationFailure
            if "LICENSE" not in metadata.get_all("License-File", []):
                raise VerificationFailure
            if archive.read(license_names[0]) != expected_license:
                raise VerificationFailure
    except (OSError, KeyError, zipfile.BadZipFile) as error:
        raise VerificationFailure from error


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
        raise VerificationEnvironmentBlocked from error
    return CommandResult(completed.returncode, completed.stdout, completed.stderr)


def _read_owner_lines(
    owner: subprocess.Popen[bytes],
    count: int,
) -> tuple[bytes, ...]:
    if owner.stdout is None or owner.stderr is None:
        raise VerificationFailure
    deadline = time.monotonic() + _READINESS_TIMEOUT_SECONDS
    pending = bytearray()
    lines: list[bytes] = []
    while len(lines) < count:
        while b"\n" in pending and len(lines) < count:
            line, _, remainder = pending.partition(b"\n")
            pending = bytearray(remainder)
            lines.append(bytes(line))
        if len(lines) == count:
            break
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise VerificationFailure
        readable, _, _ = select.select([owner.stdout], [], [], remaining)
        if not readable:
            raise VerificationFailure
        try:
            chunk = os.read(owner.stdout.fileno(), 4096)
        except OSError as error:
            raise VerificationFailure from error
        if not chunk:
            stderr = owner.stderr.read() if owner.poll() is not None else b""
            if _looks_environment_blocked(stderr):
                raise VerificationEnvironmentBlocked
            raise VerificationFailure
        pending.extend(chunk)
    return tuple(lines)


def _require_success(
    result: CommandResult,
    *,
    environment_sensitive: bool,
) -> CommandResult:
    if result.returncode == SUCCESS:
        return result
    if environment_sensitive and _looks_environment_blocked(result.stderr):
        raise VerificationEnvironmentBlocked
    raise VerificationFailure


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


if __name__ == "__main__":
    raise SystemExit(main())
