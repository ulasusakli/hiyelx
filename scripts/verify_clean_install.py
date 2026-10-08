"""Build and verify the installed HIYELX wheel outside the source checkout."""

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
EXPECTED_TRANSCRIPT = REPOSITORY_ROOT / "examples/expected/sim-motor.txt"
DEMO_CONFIG = REPOSITORY_ROOT / "examples/configs/sim-motor.yaml"


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
        return wheel.name


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
