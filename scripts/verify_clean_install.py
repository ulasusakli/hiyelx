"""Build and verify the installed HIYELX wheel outside the source checkout."""

from __future__ import annotations

import json
import os
import re
import select
import shutil
import signal
import socket
import sqlite3
import stat
import subprocess
import sys
import tempfile
import time
import uuid
import zipfile
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from email.parser import BytesParser
from email.policy import default
from pathlib import Path
from typing import cast

SUCCESS = 0
FAILURE = 1
ENVIRONMENT_BLOCKED = 2

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
EXPECTED_TRANSCRIPT = REPOSITORY_ROOT / "examples/expected/sim-motor.txt"
DEMO_CONFIG = REPOSITORY_ROOT / "examples/configs/sim-motor.yaml"
EXPECTED_LICENSE_EXPRESSION = "Apache-2.0"
RUNTIME_SESSION = "clean-install"
SECOND_RUNTIME_SESSION = "clean-install-two"
THIRD_RUNTIME_SESSION = "clean-install-three"
FOURTH_RUNTIME_SESSION = "clean-install-four"
INTERRUPT_RUNTIME_SESSION = "clean-int"
CRASH_RUNTIME_SESSION = "clean-crash"
NEGATIVE_RUNTIME_SESSION = "clean-negative"
CLEANUP_RUNTIME_SESSION = "clean-cleanup"
INITIALIZATION_LOCK_RUNTIME_SESSION = "clean-init-lock"
UNKNOWN_RUN_ID = "00000000-0000-4000-8000-000000000000"
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
_OWNER_EXIT_TIMEOUT_SECONDS = 15.0
_CLEANUP_TIMEOUT_SECONDS = 5.0
_MAX_UNIX_SOCKET_PATH_BYTES = 103
_RUNTIME_STATE_DIRECTORY_PREFIX = "hx-"
HISTORY_SUCCESS_MARKERS = (
    "history-missing-store=passed",
    "history-active-query=passed",
    "history-post-stop-query=passed",
    "history-cross-process-persistence=passed",
    "history-events-cursor-json=passed",
    "history-prune=passed",
    "history-artifact-cleanup=passed",
)
_RTO4_VERIFICATION_SUCCESS_MARKERS = (
    "rto4-wheel-built=passed",
    "rto4-source-isolation=passed",
    "rto4-env=passed",
    "rto4-events=passed",
    "rto4-interrupt=passed",
    "rto4-crash=passed",
    "rto4-prune=passed",
    "rto4-multi=passed",
    "rto4-negative=passed",
    "rto4-sanitize=passed",
    "rto4-cleanup=passed",
    "rto4-automated-acceptance=passed",
)
_RUN_NOT_FOUND = b"error: runtime run is not found\n"
_INVALID_SESSION = b"error: runtime session ID is invalid\n"
_INVALID_CONFIGURATION = b"error: runtime configuration is invalid\n"
_SESSION_ALREADY_RUNNING = b"error: runtime session is already running\n"
_SESSION_NOT_RUNNING = b"error: runtime session is not running\n"
_CONTROL_FAILED = b"error: runtime control failed\n"
_HISTORY_FAILED = b"error: runtime history failed\n"
_CLEANUP_FAILED = b"error: runtime cleanup failed\n"
_INVALID_REQUEST_REPLY = (
    b'{"error":{"code":"invalid_request","message":"control request is invalid"},'
    b'"ok":false,"protocol_version":1}\n'
)
_UNKNOWN_COMMAND_REPLY = (
    b'{"error":{"code":"unknown_command","message":"control command is unknown"},'
    b'"ok":false,"protocol_version":1}\n'
)
_FAULT_TIMEOUT_SECONDS = 3.0
_product_evidence: list[bytes] | None = None
_SUCCESS_EVENT_SEQUENCE = (
    ("runtime_start", "requested", "runtime start requested"),
    ("resource_start", "attempted", "resource start attempted"),
    ("resource_start", "succeeded", "resource start succeeded"),
    ("runtime_running", "succeeded", "runtime running"),
    ("safe_stop", "requested", "safe-stop requested"),
    ("safe_stop", "attempted", "motor safe-stop attempted"),
    ("safe_stop", "succeeded", "motor safe-stop succeeded"),
    ("safe_stop_cleanup", "completed", "safe-stop cleanup completed"),
    ("runtime_shutdown", "requested", "runtime shutdown requested"),
    ("resource_shutdown", "attempted", "resource shutdown attempted"),
    ("resource_shutdown", "succeeded", "resource shutdown succeeded"),
    ("runtime_stopped", "succeeded", "runtime stopped"),
)
_SUCCESS_EVENT_SUMMARIES = frozenset(_SUCCESS_EVENT_SEQUENCE)
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


@dataclass(frozen=True, slots=True)
class _CleanupFaultTrace:
    cleanup_calls: tuple[str, ...]
    session_cleanup_calls: tuple[bool, ...]
    persist_calls: int


CommandRunner = Callable[[Sequence[str], Path, Mapping[str, str]], CommandResult]


def main() -> int:
    """Run the clean-install gate with concise, sanitized status output."""
    try:
        wheel_name = _run_with_product_evidence()
    except KeyboardInterrupt:
        print("error: clean-install verification interrupted", file=sys.stderr)
        return FAILURE
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
    for marker in HISTORY_SUCCESS_MARKERS:
        print(marker)
    print("clean-install=passed")
    for marker in _RTO4_VERIFICATION_SUCCESS_MARKERS:
        print(marker)
    return SUCCESS


def _run_with_product_evidence() -> str:
    global _product_evidence
    previous_evidence = _product_evidence
    _product_evidence = []
    try:
        return run_clean_install_verification()
    finally:
        _product_evidence = previous_evidence


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
        isolated_home = workspace / "home"
        isolated_temp = workspace / "temp"
        isolated_home.mkdir(mode=0o700)
        isolated_temp.mkdir(mode=0o700)
        environment = _isolated_environment()
        environment["HOME"] = str(isolated_home)
        environment["TMPDIR"] = str(isolated_temp)

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
            b"scaffold=motor-driver\npackage=acme_motor_driver\nmodel=motor.acme.reference\nfiles=6"
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
                python=python,
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
    python: Path,
    workspace: Path,
    environment: Mapping[str, str],
) -> None:
    """Audit all product output while running the installed RTO-4 workflow."""
    global _product_evidence
    previous_evidence = _product_evidence
    owns_evidence = previous_evidence is None
    if owns_evidence:
        _product_evidence = []
    try:
        _verify_installed_runtime_workflow(
            executable,
            config_path,
            python=python,
            workspace=workspace,
            environment=environment,
        )
    finally:
        if owns_evidence:
            _product_evidence = previous_evidence


def _verify_installed_runtime_workflow(
    executable: Path,
    config_path: Path,
    *,
    python: Path,
    workspace: Path,
    environment: Mapping[str, str],
) -> None:
    """Prove the complete RTO-3 journey through the installed wheel CLI."""
    if sys.platform not in {"darwin", "linux"}:
        raise VerificationEnvironmentBlocked
    state_parent = _short_temporary_parent()
    with tempfile.TemporaryDirectory(
        prefix=_RUNTIME_STATE_DIRECTORY_PREFIX,
        dir=state_parent,
    ) as state_name:
        runtime_environment = dict(environment)
        runtime_environment["HIYELX_RUNTIME_STATE_DIR"] = state_name
        history_root = workspace / "history"
        runtime_environment["HIYELX_RUNTIME_HISTORY_DIR"] = str(history_root)
        for session in (
            RUNTIME_SESSION,
            SECOND_RUNTIME_SESSION,
            THIRD_RUNTIME_SESSION,
            FOURTH_RUNTIME_SESSION,
            INTERRUPT_RUNTIME_SESSION,
            CRASH_RUNTIME_SESSION,
            NEGATIVE_RUNTIME_SESSION,
            CLEANUP_RUNTIME_SESSION,
            INITIALIZATION_LOCK_RUNTIME_SESSION,
        ):
            _assert_short_control_path(Path(state_name), session)
        owners: list[tuple[subprocess.Popen[bytes], str]] = []
        primary_error: BaseException | None = None
        try:
            _verify_missing_history_store(
                executable,
                workspace=workspace,
                environment=runtime_environment,
                history_root=history_root,
            )
            first_owner = _start_installed_owner(
                executable,
                config_path,
                session=RUNTIME_SESSION,
                workspace=workspace,
                environment=runtime_environment,
                cleanup_registry=owners,
            )
            first_run = _verify_active_runtime(
                executable,
                session=RUNTIME_SESSION,
                workspace=workspace,
                environment=runtime_environment,
            )
            _stop_installed_owner(
                first_owner,
                executable,
                session=RUNTIME_SESSION,
                workspace=workspace,
                environment=runtime_environment,
                state_root=Path(state_name),
            )
            owners.remove((first_owner, RUNTIME_SESSION))
            first_events = _verify_completed_run(
                executable,
                first_run,
                workspace=workspace,
                environment=runtime_environment,
            )

            second_owner = _start_installed_owner(
                executable,
                config_path,
                session=SECOND_RUNTIME_SESSION,
                workspace=workspace,
                environment=runtime_environment,
                cleanup_registry=owners,
            )
            _verify_run_queryable(
                executable,
                first_run,
                expected_result="completed",
                workspace=workspace,
                environment=runtime_environment,
            )
            second_run = _verify_active_runtime(
                executable,
                session=SECOND_RUNTIME_SESSION,
                workspace=workspace,
                environment=runtime_environment,
            )
            if second_run == first_run:
                raise VerificationFailure
            _stop_installed_owner(
                second_owner,
                executable,
                session=SECOND_RUNTIME_SESSION,
                workspace=workspace,
                environment=runtime_environment,
                state_root=Path(state_name),
            )
            owners.remove((second_owner, SECOND_RUNTIME_SESSION))
            second_events = _verify_completed_run(
                executable,
                second_run,
                workspace=workspace,
                environment=runtime_environment,
            )
            _verify_two_run_persistence(
                executable,
                first_run=first_run,
                second_run=second_run,
                workspace=workspace,
                environment=runtime_environment,
            )
            _verify_event_queries(
                executable,
                second_run,
                second_events,
                workspace=workspace,
                environment=runtime_environment,
            )

            third_owner = _start_installed_owner(
                executable,
                config_path,
                session=THIRD_RUNTIME_SESSION,
                workspace=workspace,
                environment=runtime_environment,
                cleanup_registry=owners,
            )
            third_run = _verify_active_runtime(
                executable,
                session=THIRD_RUNTIME_SESSION,
                workspace=workspace,
                environment=runtime_environment,
            )
            fourth_owner = _start_installed_owner(
                executable,
                config_path,
                session=FOURTH_RUNTIME_SESSION,
                workspace=workspace,
                environment=runtime_environment,
                cleanup_registry=owners,
            )
            fourth_run = _verify_active_runtime(
                executable,
                session=FOURTH_RUNTIME_SESSION,
                workspace=workspace,
                environment=runtime_environment,
            )
            if third_owner.pid == fourth_owner.pid:
                raise VerificationFailure
            _assert_distinct_canonical_run_ids((first_run, second_run, third_run, fourth_run))
            _verify_b1_active_safe_prune(
                executable,
                removed_run=first_run,
                retained_finalized_run=second_run,
                retained_finalized_events=second_events,
                active_runs=(
                    (THIRD_RUNTIME_SESSION, third_run),
                    (FOURTH_RUNTIME_SESSION, fourth_run),
                ),
                workspace=workspace,
                environment=runtime_environment,
            )

            _stop_installed_owner(
                third_owner,
                executable,
                session=THIRD_RUNTIME_SESSION,
                workspace=workspace,
                environment=runtime_environment,
                state_root=Path(state_name),
            )
            owners.remove((third_owner, THIRD_RUNTIME_SESSION))
            third_events = _verify_completed_run(
                executable,
                third_run,
                workspace=workspace,
                environment=runtime_environment,
            )
            if (
                _verify_active_runtime(
                    executable,
                    session=FOURTH_RUNTIME_SESSION,
                    workspace=workspace,
                    environment=runtime_environment,
                )
                != fourth_run
            ):
                raise VerificationFailure

            _stop_installed_owner(
                fourth_owner,
                executable,
                session=FOURTH_RUNTIME_SESSION,
                workspace=workspace,
                environment=runtime_environment,
                state_root=Path(state_name),
            )
            owners.remove((fourth_owner, FOURTH_RUNTIME_SESSION))
            fourth_events = _verify_completed_run(
                executable,
                fourth_run,
                workspace=workspace,
                environment=runtime_environment,
            )
            _verify_b1_final_history(
                executable,
                removed_run=first_run,
                retained_runs=(second_run, third_run, fourth_run),
                workspace=workspace,
                environment=runtime_environment,
            )
            if len(first_events) != len(second_events):
                raise VerificationFailure
            if not (len(second_events) == len(third_events) == len(fourth_events)):
                raise VerificationFailure

            _verify_installed_interrupt_journey(
                executable,
                config_path,
                session=INTERRUPT_RUNTIME_SESSION,
                workspace=workspace,
                environment=runtime_environment,
                state_root=Path(state_name),
                cleanup_registry=owners,
            )
            _verify_installed_crash_recovery_journey(
                executable,
                config_path,
                session=CRASH_RUNTIME_SESSION,
                workspace=workspace,
                environment=runtime_environment,
                state_root=Path(state_name),
                cleanup_registry=owners,
            )
            _verify_installed_negative_acceptance(
                executable,
                config_path,
                session=NEGATIVE_RUNTIME_SESSION,
                workspace=workspace,
                environment=runtime_environment,
                state_root=Path(state_name),
                history_root=history_root,
                cleanup_registry=owners,
            )
            _verify_installed_cleanup_failure(
                python,
                executable,
                config_path,
                workspace=workspace,
                environment=runtime_environment,
                state_root=Path(state_name),
                cleanup_registry=owners,
            )
            _verify_sanitized_product_outputs(
                forbidden_paths=(
                    workspace,
                    Path(state_name),
                    history_root,
                    config_path,
                )
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            primary_error = VerificationFailure()
            primary_error.__cause__ = error
        except BaseException as error:
            primary_error = error
        cleanup_error = _cleanup_registered_owners(
            owners,
            executable,
            workspace=workspace,
            environment=runtime_environment,
        )
        if primary_error is not None:
            raise primary_error
        if cleanup_error is not None:
            raise cleanup_error
        if any(Path(state_name).iterdir()):
            raise VerificationFailure


def _verify_missing_history_store(
    executable: Path,
    *,
    workspace: Path,
    environment: Mapping[str, str],
    history_root: Path,
) -> None:
    checks = (
        (("runtime", "runs", "list"), SUCCESS, b"run-count=0\n", b""),
        (
            ("runtime", "runs", "show", UNKNOWN_RUN_ID),
            11,
            b"",
            _RUN_NOT_FOUND,
        ),
        (
            ("runtime", "events", "--run", UNKNOWN_RUN_ID),
            11,
            b"",
            _RUN_NOT_FOUND,
        ),
        (
            ("runtime", "runs", "prune", "--keep", "0"),
            SUCCESS,
            b"deleted-runs=0\n",
            b"",
        ),
    )
    for arguments, returncode, stdout, stderr in checks:
        _require_exact_result(
            _run_command((str(executable), *arguments), workspace, environment),
            returncode=returncode,
            stdout=stdout,
            stderr=stderr,
        )
        if history_root.exists():
            raise VerificationFailure


def _start_installed_owner(
    executable: Path,
    config_path: Path,
    *,
    session: str,
    workspace: Path,
    environment: Mapping[str, str],
    cleanup_registry: list[tuple[subprocess.Popen[bytes], str]] | None = None,
) -> subprocess.Popen[bytes]:
    owner = subprocess.Popen(
        (
            str(executable),
            "runtime",
            "start",
            str(config_path),
            "--session",
            session,
        ),
        cwd=workspace,
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if cleanup_registry is not None:
        cleanup_registry.append((owner, session))
    expected = (f"session={session}".encode(), b"runtime=running", b"control=ready")
    try:
        if _read_owner_lines(owner, len(expected)) != expected:
            raise VerificationFailure
    except BaseException:
        try:
            _cleanup_owner(
                owner,
                executable,
                session=session,
                workspace=workspace,
                environment=environment,
            )
        finally:
            if cleanup_registry is not None and owner.poll() is not None:
                cleanup_registry.remove((owner, session))
        raise
    return owner


def _verify_active_runtime(
    executable: Path,
    *,
    session: str,
    excluded_run_ids: Sequence[str] = (),
    workspace: Path,
    environment: Mapping[str, str],
) -> str:
    status = _require_success(
        _run_command(
            (str(executable), "runtime", "status", "--session", session),
            workspace,
            environment,
        ),
        environment_sensitive=False,
    )
    expected_status = EXPECTED_RUNTIME_STATUS.replace(
        b"session=clean-install\n", f"session={session}\n".encode(), 1
    )
    if status.stdout != expected_status or status.stderr:
        raise VerificationFailure
    listing = _load_canonical_json_result(
        _run_command(
            (str(executable), "runtime", "runs", "list", "--json"),
            workspace,
            environment,
        )
    )
    raw_runs_value = listing.get("runs")
    if not isinstance(raw_runs_value, list):
        raise VerificationFailure
    raw_runs = cast(list[object], raw_runs_value)
    if listing.get("run_count") != len(raw_runs):
        raise VerificationFailure
    runs = [cast(dict[str, object], run) for run in raw_runs if isinstance(run, dict)]
    if len(runs) != len(raw_runs):
        raise VerificationFailure
    matching = [
        run
        for run in runs
        if run.get("session_id") == session and run.get("run_id") not in excluded_run_ids
    ]
    if len(matching) != 1 or matching[0].get("result") is not None:
        raise VerificationFailure
    run_id = matching[0].get("run_id")
    if not isinstance(run_id, str):
        raise VerificationFailure
    shown = _load_canonical_json_result(
        _run_command(
            (str(executable), "runtime", "runs", "show", run_id, "--json"),
            workspace,
            environment,
        )
    )
    if shown != matching[0] or shown.get("ended_at") is not None:
        raise VerificationFailure
    events = _load_event_page(
        _run_command(
            (str(executable), "runtime", "events", "--run", run_id, "--json"),
            workspace,
            environment,
        ),
        run_id=run_id,
    )
    _assert_exact_success_events(events, count=4)
    if shown.get("event_high_water_mark") != 3:
        raise VerificationFailure
    return run_id


def _stop_installed_owner(
    owner: subprocess.Popen[bytes],
    executable: Path,
    *,
    session: str,
    workspace: Path,
    environment: Mapping[str, str],
    state_root: Path,
) -> None:
    stopped = _require_success(
        _run_command(
            (str(executable), "runtime", "stop", "--session", session),
            workspace,
            environment,
        ),
        environment_sensitive=False,
    )
    expected = f"session={session}\nruntime=stopped\n".encode()
    if stopped.stdout != expected or stopped.stderr:
        raise VerificationFailure
    try:
        remaining_stdout, remaining_stderr = owner.communicate(timeout=_OWNER_EXIT_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired as error:
        _cleanup_owner(
            owner,
            executable,
            session=session,
            workspace=workspace,
            environment=environment,
        )
        raise VerificationFailure from error
    _record_product_output(remaining_stdout, remaining_stderr)
    if (
        owner.returncode != SUCCESS
        or remaining_stdout != b"runtime=stopped\n"
        or remaining_stderr
        or (state_root / session).exists()
    ):
        raise VerificationFailure


def _verify_installed_interrupt_journey(
    executable: Path,
    config_path: Path,
    *,
    session: str,
    workspace: Path,
    environment: Mapping[str, str],
    state_root: Path,
    cleanup_registry: list[tuple[subprocess.Popen[bytes], str]],
) -> None:
    owner = _start_installed_owner(
        executable,
        config_path,
        session=session,
        workspace=workspace,
        environment=environment,
        cleanup_registry=cleanup_registry,
    )
    run_id = _verify_active_runtime(
        executable,
        session=session,
        workspace=workspace,
        environment=environment,
    )
    owner.send_signal(signal.SIGINT)
    _verify_owner_exit(
        owner,
        executable,
        session=session,
        workspace=workspace,
        environment=environment,
        expected_returncode=SUCCESS,
        expected_stdout=b"runtime=stopped\n",
        expected_stderr=b"",
    )
    if (state_root / session).exists():
        raise VerificationFailure
    cleanup_registry.remove((owner, session))
    _verify_interrupted_run(
        executable,
        run_id,
        workspace=workspace,
        environment=environment,
    )


def _verify_installed_crash_recovery_journey(
    executable: Path,
    config_path: Path,
    *,
    session: str,
    workspace: Path,
    environment: Mapping[str, str],
    state_root: Path,
    cleanup_registry: list[tuple[subprocess.Popen[bytes], str]],
) -> None:
    crashed_owner = _start_installed_owner(
        executable,
        config_path,
        session=session,
        workspace=workspace,
        environment=environment,
        cleanup_registry=cleanup_registry,
    )
    crashed_run = _verify_active_runtime(
        executable,
        session=session,
        workspace=workspace,
        environment=environment,
    )
    crashed_owner.kill()
    _verify_owner_exit(
        crashed_owner,
        executable,
        session=session,
        workspace=workspace,
        environment=environment,
        expected_returncode=None,
        expected_stdout=b"",
        expected_stderr=b"",
        require_signal_returncode=True,
    )
    cleanup_registry.remove((crashed_owner, session))
    crashed_document, crashed_events = _verify_incomplete_run(
        executable,
        crashed_run,
        session=session,
        workspace=workspace,
        environment=environment,
    )

    recovery_owner = _start_installed_owner(
        executable,
        config_path,
        session=session,
        workspace=workspace,
        environment=environment,
        cleanup_registry=cleanup_registry,
    )
    recovery_run = _verify_active_runtime(
        executable,
        session=session,
        excluded_run_ids=(crashed_run,),
        workspace=workspace,
        environment=environment,
    )
    _assert_distinct_canonical_run_ids((crashed_run, recovery_run))
    _assert_incomplete_run_unchanged(
        executable,
        crashed_run,
        session=session,
        expected_document=crashed_document,
        expected_events=crashed_events,
        workspace=workspace,
        environment=environment,
    )
    _stop_installed_owner(
        recovery_owner,
        executable,
        session=session,
        workspace=workspace,
        environment=environment,
        state_root=state_root,
    )
    cleanup_registry.remove((recovery_owner, session))
    _verify_completed_run(
        executable,
        recovery_run,
        workspace=workspace,
        environment=environment,
    )
    _assert_incomplete_run_unchanged(
        executable,
        crashed_run,
        session=session,
        expected_document=crashed_document,
        expected_events=crashed_events,
        workspace=workspace,
        environment=environment,
    )
    if (state_root / session).exists():
        raise VerificationFailure


def _verify_owner_exit(
    owner: subprocess.Popen[bytes],
    executable: Path,
    *,
    session: str,
    workspace: Path,
    environment: Mapping[str, str],
    expected_returncode: int | None,
    expected_stdout: bytes,
    expected_stderr: bytes,
    require_signal_returncode: bool = False,
) -> None:
    try:
        remaining_stdout, remaining_stderr = owner.communicate(timeout=_OWNER_EXIT_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired as error:
        _cleanup_owner(
            owner,
            executable,
            session=session,
            workspace=workspace,
            environment=environment,
        )
        raise VerificationFailure from error
    _record_product_output(remaining_stdout, remaining_stderr)
    if require_signal_returncode:
        if owner.returncode is None or owner.returncode >= 0:
            raise VerificationFailure
    elif owner.returncode != expected_returncode:
        raise VerificationFailure
    if remaining_stdout != expected_stdout or remaining_stderr != expected_stderr:
        raise VerificationFailure


def _verify_completed_run(
    executable: Path,
    run_id: str,
    *,
    workspace: Path,
    environment: Mapping[str, str],
) -> list[dict[str, object]]:
    run = _verify_run_queryable(
        executable,
        run_id,
        expected_result="completed",
        workspace=workspace,
        environment=environment,
    )
    if (
        run.get("stop_reason") != "cli_stop"
        or not isinstance(run.get("ended_at"), str)
        or run.get("event_high_water_mark") != 11
    ):
        raise VerificationFailure
    events = _load_event_page(
        _run_command(
            (str(executable), "runtime", "events", "--run", run_id, "--json"),
            workspace,
            environment,
        ),
        run_id=run_id,
    )
    _assert_exact_success_events(events, count=12)
    return events


def _verify_interrupted_run(
    executable: Path,
    run_id: str,
    *,
    workspace: Path,
    environment: Mapping[str, str],
) -> list[dict[str, object]]:
    run = _verify_run_queryable(
        executable,
        run_id,
        expected_result="interrupted",
        workspace=workspace,
        environment=environment,
    )
    if (
        run.get("stop_reason") != "sigint"
        or not _is_canonical_timestamp(run.get("ended_at"))
        or run.get("event_high_water_mark") != 11
    ):
        raise VerificationFailure
    events = _load_event_page(
        _run_command(
            (str(executable), "runtime", "events", "--run", run_id, "--json"),
            workspace,
            environment,
        ),
        run_id=run_id,
    )
    _assert_exact_success_events(events, count=12)
    return events


def _verify_incomplete_run(
    executable: Path,
    run_id: str,
    *,
    session: str,
    workspace: Path,
    environment: Mapping[str, str],
) -> tuple[dict[str, object], list[dict[str, object]]]:
    run = _verify_run_queryable(
        executable,
        run_id,
        expected_result=None,
        workspace=workspace,
        environment=environment,
    )
    if (
        run.get("session_id") != session
        or run.get("ended_at") is not None
        or run.get("stop_reason") is not None
        or run.get("event_high_water_mark") != 3
    ):
        raise VerificationFailure
    events = _load_event_page(
        _run_command(
            (str(executable), "runtime", "events", "--run", run_id, "--json"),
            workspace,
            environment,
        ),
        run_id=run_id,
    )
    _assert_exact_success_events(events, count=4)
    return run, events


def _assert_incomplete_run_unchanged(
    executable: Path,
    run_id: str,
    *,
    session: str,
    expected_document: dict[str, object],
    expected_events: list[dict[str, object]],
    workspace: Path,
    environment: Mapping[str, str],
) -> None:
    document, events = _verify_incomplete_run(
        executable,
        run_id,
        session=session,
        workspace=workspace,
        environment=environment,
    )
    if document != expected_document or events != expected_events:
        raise VerificationFailure


def _is_canonical_timestamp(value: object) -> bool:
    if not isinstance(value, str) or len(value) != 27 or not value.endswith("Z"):
        return False
    try:
        parsed = datetime.fromisoformat(value.removesuffix("Z") + "+00:00")
    except ValueError:
        return False
    return parsed.strftime("%Y-%m-%dT%H:%M:%S.%fZ") == value


def _verify_run_queryable(
    executable: Path,
    run_id: str,
    *,
    expected_result: str | None,
    workspace: Path,
    environment: Mapping[str, str],
) -> dict[str, object]:
    run = _load_canonical_json_result(
        _run_command(
            (str(executable), "runtime", "runs", "show", run_id, "--json"),
            workspace,
            environment,
        )
    )
    if run.get("run_id") != run_id or run.get("result") != expected_result:
        raise VerificationFailure
    return run


def _verify_installed_negative_acceptance(
    executable: Path,
    config_path: Path,
    *,
    session: str,
    workspace: Path,
    environment: Mapping[str, str],
    state_root: Path,
    history_root: Path,
    cleanup_registry: list[tuple[subprocess.Popen[bytes], str]],
) -> None:
    """Exercise the installed CLI, wire, control-path, and history fault matrix."""
    fault_root = workspace / "rto4-faults"
    fault_root.mkdir(mode=0o700)
    _verify_invalid_cli_inputs(
        executable,
        config_path,
        workspace=workspace,
        environment=environment,
        state_root=state_root,
        history_root=history_root,
    )

    owner = _start_installed_owner(
        executable,
        config_path,
        session=session,
        workspace=workspace,
        environment=environment,
        cleanup_registry=cleanup_registry,
    )
    run_id = _verify_active_runtime(
        executable,
        session=session,
        workspace=workspace,
        environment=environment,
    )
    before_run, before_events = _verify_incomplete_run(
        executable,
        run_id,
        session=session,
        workspace=workspace,
        environment=environment,
    )
    _require_bounded_exact_result(
        (str(executable), "runtime", "start", str(config_path), "--session", session),
        workspace=workspace,
        environment=environment,
        returncode=4,
        stdout=b"",
        stderr=_SESSION_ALREADY_RUNNING,
    )
    _assert_incomplete_run_unchanged(
        executable,
        run_id,
        session=session,
        expected_document=before_run,
        expected_events=before_events,
        workspace=workspace,
        environment=environment,
    )
    _verify_private_control_probes(
        state_root / session / "control.sock",
        session=session,
    )
    if (
        _verify_active_runtime(
            executable,
            session=session,
            workspace=workspace,
            environment=environment,
        )
        != run_id
    ):
        raise VerificationFailure
    _assert_incomplete_run_unchanged(
        executable,
        run_id,
        session=session,
        expected_document=before_run,
        expected_events=before_events,
        workspace=workspace,
        environment=environment,
    )
    _stop_installed_owner(
        owner,
        executable,
        session=session,
        workspace=workspace,
        environment=environment,
        state_root=state_root,
    )
    cleanup_registry.remove((owner, session))
    _verify_completed_run(
        executable,
        run_id,
        workspace=workspace,
        environment=environment,
    )

    _verify_control_fault_fixtures(
        executable,
        fault_root=fault_root,
        workspace=workspace,
        environment=environment,
    )
    _verify_history_fault_fixtures(
        executable,
        source_history=history_root,
        fault_root=fault_root,
        workspace=workspace,
        environment=environment,
    )
    _verify_busy_history_fault(
        executable,
        source_history=history_root,
        fault_root=fault_root,
        workspace=workspace,
        environment=environment,
    )
    _verify_initialization_lock_fault(
        executable,
        config_path,
        fault_root=fault_root,
        state_root=state_root,
        workspace=workspace,
        environment=environment,
    )


def _verify_invalid_cli_inputs(
    executable: Path,
    config_path: Path,
    *,
    workspace: Path,
    environment: Mapping[str, str],
    state_root: Path,
    history_root: Path,
) -> None:
    before = (_tree_snapshot(state_root), _tree_snapshot(history_root))
    invalid_config = workspace / "invalid-runtime.yaml"
    invalid_config.write_text("schema_version: [\n", encoding="utf-8")
    unsupported_config = workspace / "unsupported-runtime.yaml"
    unsupported_config.write_text(
        'schema_version: "1"\nresources:\n'
        "  - identity: unsupported_motor\n"
        "    model: motor.unsupported\n"
        "    settings: {}\n",
        encoding="utf-8",
    )
    exact_cases = (
        (("runtime", "status", "--session", "../private"), 3, _INVALID_SESSION),
        (("runtime", "stop", "--session", "../private"), 3, _INVALID_SESSION),
        (
            ("runtime", "start", str(config_path), "--session", "../private"),
            3,
            _INVALID_SESSION,
        ),
        (
            ("runtime", "start", str(invalid_config), "--session", "valid"),
            2,
            _INVALID_CONFIGURATION,
        ),
        (
            ("runtime", "start", str(unsupported_config), "--session", "valid"),
            2,
            _INVALID_CONFIGURATION,
        ),
        (("runtime", "status", "--session", "missing"), 5, _SESSION_NOT_RUNNING),
        (("runtime", "stop", "--session", "missing"), 5, _SESSION_NOT_RUNNING),
        (("runtime", "runs", "show", UNKNOWN_RUN_ID), 11, _RUN_NOT_FOUND),
        (("runtime", "runs", "show", "not-a-run"), 11, _RUN_NOT_FOUND),
        (("runtime", "events", "--run", UNKNOWN_RUN_ID), 11, _RUN_NOT_FOUND),
        (("runtime", "events", "--run", "not-a-run"), 11, _RUN_NOT_FOUND),
    )
    for arguments, returncode, stderr in exact_cases:
        _require_bounded_exact_result(
            (str(executable), *arguments),
            workspace=workspace,
            environment=environment,
            returncode=returncode,
            stdout=b"",
            stderr=stderr,
        )

    parser_cases = (
        (("runtime", "runs", "list", "--limit", value), _list_limit_error())
        for value in ("0", "101", "not-an-integer")
    )
    event_after_cases = (
        (("runtime", "events", "--run", UNKNOWN_RUN_ID, "--after", value), _event_after_error())
        for value in ("-2", "not-an-integer")
    )
    event_limit_cases = (
        (("runtime", "events", "--run", UNKNOWN_RUN_ID, "--limit", value), _event_limit_error())
        for value in ("0", "1001")
    )
    prune_cases = (
        (("runtime", "runs", "prune"), _prune_missing_error()),
        (("runtime", "runs", "prune", "--keep", "-1"), _prune_value_error()),
        (
            ("runtime", "runs", "prune", "--keep", "9223372036854775808"),
            _prune_value_error(),
        ),
        (
            ("runtime", "runs", "prune", "--keep", "not-an-integer"),
            _prune_value_error(),
        ),
    )
    for arguments, stderr in (
        *parser_cases,
        *event_after_cases,
        *event_limit_cases,
        *prune_cases,
    ):
        _require_bounded_exact_result(
            (str(executable), *arguments),
            workspace=workspace,
            environment=environment,
            returncode=2,
            stdout=b"",
            stderr=stderr,
        )
    if before != (_tree_snapshot(state_root), _tree_snapshot(history_root)):
        raise VerificationFailure


def _list_limit_error() -> bytes:
    return (
        b"usage: hiyelx runtime runs list [-h] [--limit LIMIT] [--json]\n"
        b"hiyelx runtime runs list: error: argument --limit: "
        b"limit must be between 1 and 100\n"
    )


def _event_after_error() -> bytes:
    return (
        b"usage: hiyelx runtime events [-h] --run RUN_ID [--after AFTER] [--limit LIMIT]\n"
        b"                             [--json]\n"
        b"hiyelx runtime events: error: argument --after: "
        b"after must be an integer at or above -1\n"
    )


def _event_limit_error() -> bytes:
    return (
        b"usage: hiyelx runtime events [-h] --run RUN_ID [--after AFTER] [--limit LIMIT]\n"
        b"                             [--json]\n"
        b"hiyelx runtime events: error: argument --limit: "
        b"limit must be between 1 and 1000\n"
    )


def _prune_missing_error() -> bytes:
    return (
        b"usage: hiyelx runtime runs prune [-h] --keep KEEP\n"
        b"hiyelx runtime runs prune: error: the following arguments are required: --keep\n"
    )


def _prune_value_error() -> bytes:
    return (
        b"usage: hiyelx runtime runs prune [-h] --keep KEEP\n"
        b"hiyelx runtime runs prune: error: argument --keep: "
        b"keep must be between 0 and 9223372036854775807\n"
    )


def _verify_private_control_probes(socket_path: Path, *, session: str) -> None:
    valid_without_newline = json.dumps(
        {"command": "status", "protocol_version": 1, "session": session},
        separators=(",", ":"),
        sort_keys=True,
    ).encode("ascii")
    invalid_messages = (
        (b'{"command":\n', False),
        (valid_without_newline, True),
        (b'{"command":"status","protocol_version":1}\n', False),
        (b'{"command":1,"protocol_version":1,"session":"' + session.encode() + b'"}\n', False),
        (
            b'{"command":"status","command":"status","protocol_version":1,"session":"'
            + session.encode()
            + b'"}\n',
            False,
        ),
        (
            b'{"command":"status","protocol_version":true,"session":"' + session.encode() + b'"}\n',
            False,
        ),
        (
            b'{"command":"status","protocol_version":1.0,"session":"' + session.encode() + b'"}\n',
            False,
        ),
        (
            b'{"command":"status","protocol_version":2,"session":"' + session.encode() + b'"}\n',
            False,
        ),
        (b"x" * 8193 + b"\n", False),
    )
    for message, shutdown_write in invalid_messages:
        reply = _raw_control_request(
            socket_path,
            message,
            shutdown_write=shutdown_write,
        )
        if reply != _INVALID_REQUEST_REPLY:
            raise VerificationFailure
        _record_product_output(reply)
    unknown = (
        json.dumps(
            {"command": "unknown", "protocol_version": 1, "session": session},
            separators=(",", ":"),
            sort_keys=True,
        ).encode("ascii")
        + b"\n"
    )
    reply = _raw_control_request(socket_path, unknown, shutdown_write=False)
    if reply != _UNKNOWN_COMMAND_REPLY:
        raise VerificationFailure
    _record_product_output(reply)


def _raw_control_request(
    socket_path: Path,
    message: bytes,
    *,
    shutdown_write: bool,
) -> bytes:
    connection = socket.socket(socket.AF_UNIX)
    connection.settimeout(_FAULT_TIMEOUT_SECONDS)
    response = bytearray()
    try:
        connection.connect(str(socket_path))
        connection.sendall(message)
        if shutdown_write:
            connection.shutdown(socket.SHUT_WR)
        while not response.endswith(b"\n"):
            chunk = connection.recv(8193)
            if not chunk or len(response) + len(chunk) > 8193:
                raise VerificationFailure
            response.extend(chunk)
        if connection.recv(1) != b"":
            raise VerificationFailure
    except (OSError, TimeoutError) as error:
        raise VerificationFailure from error
    finally:
        connection.close()
    return bytes(response)


def _verify_control_fault_fixtures(
    executable: Path,
    *,
    fault_root: Path,
    workspace: Path,
    environment: Mapping[str, str],
) -> None:
    control_root = fault_root / "control"
    control_root.mkdir(mode=0o700)
    cases: list[Path] = []

    unsafe = control_root / "unsafe-root"
    unsafe.mkdir(mode=0o755)
    cases.append(unsafe)

    symlink_root = control_root / "symlink-root"
    symlink_root.mkdir(mode=0o700)
    target = control_root / "symlink-target"
    target.mkdir(mode=0o700)
    (symlink_root / "fault").symlink_to(target, target_is_directory=True)
    cases.append(symlink_root)

    wrong_type = control_root / "wrong-type-root"
    wrong_type.mkdir(mode=0o700)
    (wrong_type / "fault").write_bytes(b"keep")
    os.chmod(wrong_type / "fault", 0o600)
    cases.append(wrong_type)

    missing_lock = control_root / "missing-lock-root"
    (missing_lock / "fault").mkdir(parents=True, mode=0o700)
    cases.append(missing_lock)

    unknown = control_root / "unknown-root"
    unknown_session = unknown / "fault"
    unknown_session.mkdir(parents=True, mode=0o700)
    (unknown_session / "owner.lock").write_bytes(b"")
    (unknown_session / "unknown.entry").write_bytes(b"keep")
    os.chmod(unknown_session / "owner.lock", 0o600)
    os.chmod(unknown_session / "unknown.entry", 0o600)
    cases.append(unknown)

    unsafe_manifest = control_root / "unsafe-manifest-root"
    unsafe_session = unsafe_manifest / "fault"
    unsafe_session.mkdir(parents=True, mode=0o700)
    (unsafe_session / "owner.lock").write_bytes(b"")
    (unsafe_session / "manifest.json").write_bytes(b"keep")
    os.chmod(unsafe_session / "owner.lock", 0o600)
    os.chmod(unsafe_session / "manifest.json", 0o644)
    cases.append(unsafe_manifest)

    for root in cases:
        before = _tree_snapshot(control_root)
        fault_environment = dict(environment)
        fault_environment["HIYELX_RUNTIME_STATE_DIR"] = str(root)
        _require_bounded_exact_result(
            (str(executable), "runtime", "status", "--session", "fault"),
            workspace=workspace,
            environment=fault_environment,
            returncode=6,
            stdout=b"",
            stderr=_CONTROL_FAILED,
        )
        if _tree_snapshot(control_root) != before:
            raise VerificationFailure


def _verify_history_fault_fixtures(
    executable: Path,
    *,
    source_history: Path,
    fault_root: Path,
    workspace: Path,
    environment: Mapping[str, str],
) -> None:
    history_fixtures = fault_root / "history"
    history_fixtures.mkdir(mode=0o700)
    source_connection = sqlite3.connect(source_history / "history.sqlite3")
    try:
        event_row = source_connection.execute(
            "SELECT run_id FROM events ORDER BY run_id, sequence LIMIT 1"
        ).fetchone()
    finally:
        source_connection.close()
    if event_row is None or not isinstance(event_row[0], str):
        raise VerificationFailure
    event_run_id = event_row[0]
    unsafe = history_fixtures / "unsafe-root"
    unsafe.mkdir(mode=0o755)

    unsafe_database_mode, unsafe_lock_mode = _create_unsafe_history_mode_fixtures(
        source_history,
        history_fixtures=history_fixtures,
    )

    symlink_root = history_fixtures / "symlink"
    symlink_root.mkdir(mode=0o700)
    target = history_fixtures / "symlink-target"
    target.write_bytes(b"keep")
    os.chmod(target, 0o600)
    (symlink_root / "history.sqlite3").symlink_to(target)

    wrong_type = history_fixtures / "wrong-type"
    wrong_type.mkdir(mode=0o700)
    (wrong_type / "history.sqlite3").mkdir(mode=0o700)

    unknown = history_fixtures / "unknown"
    unknown.mkdir(mode=0o700)
    (unknown / "unknown.entry").write_bytes(b"keep")
    os.chmod(unknown / "unknown.entry", 0o600)

    fixture_mutators: tuple[tuple[str, Callable[[Path], None]], ...] = (
        ("user-version", lambda database: _execute_sql(database, "PRAGMA user_version = 2")),
        (
            "object-drift",
            lambda database: _execute_sql(database, "CREATE TABLE unexpected(value TEXT)"),
        ),
        (
            "column-drift",
            lambda database: _replace_schema_sql(
                database, "runs", "package_version TEXT", "package_release TEXT"
            ),
        ),
        ("index-drift", lambda database: _execute_sql(database, "DROP INDEX runs_order")),
        (
            "fk-drift",
            lambda database: _replace_schema_sql(
                database, "events", "ON DELETE CASCADE", "ON DELETE RESTRICT"
            ),
        ),
        (
            "run-corrupt",
            lambda database: _execute_sql(
                database,
                "PRAGMA ignore_check_constraints = ON; UPDATE runs SET session_id = '../private'",
            ),
        ),
        (
            "event-corrupt",
            lambda database: _execute_sql(
                database,
                "PRAGMA ignore_check_constraints = ON; "
                "UPDATE events SET summary = 'private' || char(10) || 'summary' "
                "WHERE sequence = 0",
            ),
        ),
        (
            "event-gap",
            lambda database: _execute_sql(database, "DELETE FROM events WHERE sequence = 1"),
        ),
        (
            "watermark-corrupt",
            lambda database: _execute_sql(
                database,
                "PRAGMA ignore_check_constraints = ON; UPDATE runs SET event_high_water_mark = 10",
            ),
        ),
    )
    roots: list[tuple[Path, tuple[str, ...]]] = [
        (root, ("runtime", "runs", "list"))
        for root in (
            unsafe,
            unsafe_database_mode,
            unsafe_lock_mode,
            symlink_root,
            wrong_type,
            unknown,
        )
    ]
    for name, mutate in fixture_mutators:
        root = history_fixtures / name
        shutil.copytree(source_history, root)
        mutate(root / "history.sqlite3")
        arguments = _history_fault_arguments(name, event_run_id=event_run_id)
        roots.append((root, arguments))

    for root, arguments in roots:
        before = _tree_snapshot(root)
        fault_environment = dict(environment)
        fault_environment["HIYELX_RUNTIME_HISTORY_DIR"] = str(root)
        _require_bounded_exact_result(
            (str(executable), *arguments),
            workspace=workspace,
            environment=fault_environment,
            returncode=10,
            stdout=b"",
            stderr=_HISTORY_FAILED,
        )
        if _tree_snapshot(root) != before:
            raise VerificationFailure


def _create_unsafe_history_mode_fixtures(
    source_history: Path,
    *,
    history_fixtures: Path,
) -> tuple[Path, Path]:
    unsafe_database_mode = history_fixtures / "unsafe-database-mode"
    shutil.copytree(source_history, unsafe_database_mode)
    database = unsafe_database_mode / "history.sqlite3"
    if not database.is_file():
        raise VerificationFailure
    os.chmod(database, 0o644)

    unsafe_lock_mode = history_fixtures / "unsafe-lock-mode"
    shutil.copytree(source_history, unsafe_lock_mode)
    lock = unsafe_lock_mode / "history.lock"
    if not lock.is_file():
        raise VerificationFailure
    os.chmod(lock, 0o644)
    return unsafe_database_mode, unsafe_lock_mode


def _history_fault_arguments(name: str, *, event_run_id: str) -> tuple[str, ...]:
    if name in {"event-corrupt", "event-gap", "watermark-corrupt"}:
        return ("runtime", "events", "--run", event_run_id)
    return ("runtime", "runs", "list")


def _execute_sql(database: Path, script: str) -> None:
    connection = sqlite3.connect(database)
    try:
        connection.executescript(script)
        connection.commit()
    finally:
        connection.close()


def _replace_schema_sql(
    database: Path,
    object_name: str,
    old: str,
    new: str,
) -> None:
    connection = sqlite3.connect(database)
    try:
        row = connection.execute(
            "SELECT sql FROM sqlite_schema WHERE name = ?", (object_name,)
        ).fetchone()
        if row is None or not isinstance(row[0], str) or old not in row[0]:
            raise VerificationFailure
        connection.execute("PRAGMA writable_schema = ON")
        connection.execute(
            "UPDATE sqlite_schema SET sql = ? WHERE name = ?",
            (row[0].replace(old, new), object_name),
        )
        version = connection.execute("PRAGMA schema_version").fetchone()
        if version is None or type(version[0]) is not int:
            raise VerificationFailure
        connection.execute(f"PRAGMA schema_version = {version[0] + 1}")
        connection.commit()
    finally:
        connection.close()


def _verify_busy_history_fault(
    executable: Path,
    *,
    source_history: Path,
    fault_root: Path,
    workspace: Path,
    environment: Mapping[str, str],
) -> None:
    root = fault_root / "history-busy"
    shutil.copytree(source_history, root)
    database = root / "history.sqlite3"
    holder_script = """
import sqlite3
import sys
import time

connection = sqlite3.connect(sys.argv[1], isolation_level=None)
connection.execute("PRAGMA journal_mode = WAL")
connection.execute("BEGIN IMMEDIATE")
connection.execute(
    "UPDATE runs SET run_id = run_id WHERE rowid = (SELECT rowid FROM runs LIMIT 1)"
)
print("writer-lock=ready", flush=True)
time.sleep(30)
"""
    holder = subprocess.Popen(
        (str(executable.parent / "python"), "-c", holder_script, str(database)),
        cwd=workspace,
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        if _read_fault_holder_ready(holder) != b"writer-lock=ready\n":
            raise VerificationFailure
        reader = sqlite3.connect(database)
        try:
            count = reader.execute("SELECT COUNT(*) FROM runs").fetchone()
        finally:
            reader.close()
        fault_environment = dict(environment)
        fault_environment["HIYELX_RUNTIME_HISTORY_DIR"] = str(root)
        _require_bounded_exact_result(
            (str(executable), "runtime", "runs", "prune", "--keep", "0"),
            workspace=workspace,
            environment=fault_environment,
            returncode=10,
            stdout=b"",
            stderr=_HISTORY_FAILED,
        )
    finally:
        _reap_fault_holder(holder)
    reader = sqlite3.connect(database)
    try:
        if reader.execute("SELECT COUNT(*) FROM runs").fetchone() != count:
            raise VerificationFailure
    finally:
        reader.close()


def _read_fault_holder_ready(holder: subprocess.Popen[bytes]) -> bytes:
    if holder.stdout is None or holder.stderr is None:
        raise VerificationFailure
    readable, _, _ = select.select([holder.stdout], [], [], _FAULT_TIMEOUT_SECONDS)
    if not readable:
        raise VerificationFailure
    line = holder.stdout.readline()
    if holder.poll() is not None:
        raise VerificationFailure
    return line


def _reap_fault_holder(holder: subprocess.Popen[bytes]) -> None:
    if holder.poll() is None:
        holder.terminate()
        try:
            holder.wait(timeout=_CLEANUP_TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired:
            holder.kill()
            try:
                holder.wait(timeout=_CLEANUP_TIMEOUT_SECONDS)
            except subprocess.TimeoutExpired as error:
                raise VerificationFailure from error
    if holder.stdout is not None:
        holder.stdout.close()
    if holder.stderr is not None:
        holder.stderr.close()


def _verify_initialization_lock_fault(
    executable: Path,
    config_path: Path,
    *,
    fault_root: Path,
    state_root: Path,
    workspace: Path,
    environment: Mapping[str, str],
) -> None:
    import fcntl

    root = fault_root / "history-init-lock"
    root.mkdir(mode=0o700)
    lock = root / "history.lock"
    lock.write_bytes(b"")
    os.chmod(lock, 0o600)
    descriptor = os.open(lock, os.O_RDWR)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        before = _tree_snapshot(root)
        fault_environment = dict(environment)
        fault_environment["HIYELX_RUNTIME_HISTORY_DIR"] = str(root)
        _require_bounded_exact_result(
            (
                str(executable),
                "runtime",
                "start",
                str(config_path),
                "--session",
                INITIALIZATION_LOCK_RUNTIME_SESSION,
            ),
            workspace=workspace,
            environment=fault_environment,
            returncode=10,
            stdout=b"",
            stderr=_HISTORY_FAILED,
        )
        if (
            _tree_snapshot(root) != before
            or (state_root / INITIALIZATION_LOCK_RUNTIME_SESSION).exists()
        ):
            raise VerificationFailure
    finally:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


def _verify_installed_cleanup_failure(
    python: Path,
    executable: Path,
    config_path: Path,
    *,
    workspace: Path,
    environment: Mapping[str, str],
    state_root: Path,
    cleanup_registry: list[tuple[subprocess.Popen[bytes], str]],
) -> _CleanupFaultTrace:
    history_root = workspace / "cleanup-failure-history"
    trace_path = workspace / "cleanup-failure-trace.json"
    fault_environment = dict(environment)
    fault_environment["HIYELX_RUNTIME_HISTORY_DIR"] = str(history_root)
    harness = """
import json
import sys
from pathlib import Path
from hiyelx import cli
from hiyelx.runtime import control

cleanup_calls = []
session_cleanup_calls = []
persist_calls = []
original_safe_stop = control.RuntimeOperations.safe_stop
original_shutdown = control.RuntimeOperations.shutdown
original_cleanup = control.OwnedSession.cleanup
original_persist = control.HistoryStore.persist_events

async def fail_safe_stop(operations):
    cleanup_calls.append("safe_stop")
    raise RuntimeError("private safe-stop failure")

async def record_shutdown(operations):
    cleanup_calls.append("shutdown")
    await original_shutdown(operations)

def fail_then_finish(owned, *, final=False):
    session_cleanup_calls.append(final)
    if not final:
        return False
    return original_cleanup(owned, final=True)

def fail_secondary_persist(store, *args, **kwargs):
    persist_calls.append(True)
    if len(persist_calls) == 2:
        raise RuntimeError("private secondary persistence failure")
    return original_persist(store, *args, **kwargs)

control.RuntimeOperations.safe_stop = fail_safe_stop
control.RuntimeOperations.shutdown = record_shutdown
control.OwnedSession.cleanup = fail_then_finish
control.HistoryStore.persist_events = fail_secondary_persist
code = cli.main(["runtime", "start", sys.argv[1], "--session", sys.argv[2]])
Path(sys.argv[3]).write_text(
    json.dumps(
        {
            "cleanup_calls": cleanup_calls,
            "persist_calls": len(persist_calls),
            "session_cleanup_calls": session_cleanup_calls,
        },
        separators=(",", ":"),
        sort_keys=True,
    )
    + "\\n",
    encoding="utf-8",
)
raise SystemExit(code)
"""
    owner = subprocess.Popen(
        (
            str(python),
            "-c",
            harness,
            str(config_path),
            CLEANUP_RUNTIME_SESSION,
            str(trace_path),
        ),
        cwd=workspace,
        env=fault_environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    cleanup_registry.append((owner, CLEANUP_RUNTIME_SESSION))
    expected = (
        f"session={CLEANUP_RUNTIME_SESSION}".encode(),
        b"runtime=running",
        b"control=ready",
    )
    if _read_owner_lines(owner, len(expected)) != expected:
        raise VerificationFailure
    stop = _run_command(
        (str(executable), "runtime", "stop", "--session", CLEANUP_RUNTIME_SESSION),
        workspace,
        fault_environment,
    )
    _require_exact_result(stop, returncode=8, stdout=b"", stderr=_CLEANUP_FAILED)
    try:
        remaining_stdout, remaining_stderr = owner.communicate(timeout=_OWNER_EXIT_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired as error:
        _cleanup_owner(
            owner,
            executable,
            session=CLEANUP_RUNTIME_SESSION,
            workspace=workspace,
            environment=fault_environment,
        )
        raise VerificationFailure from error
    _record_product_output(remaining_stdout, remaining_stderr)
    try:
        trace = _load_cleanup_fault_trace(trace_path)
    finally:
        trace_path.unlink(missing_ok=True)
    if (
        owner.returncode != 8
        or remaining_stdout
        or remaining_stderr != _CLEANUP_FAILED
        or (state_root / CLEANUP_RUNTIME_SESSION).exists()
        or trace
        != _CleanupFaultTrace(
            cleanup_calls=("safe_stop", "shutdown"),
            session_cleanup_calls=(False, True),
            persist_calls=2,
        )
    ):
        raise VerificationFailure
    cleanup_registry.remove((owner, CLEANUP_RUNTIME_SESSION))
    document, runs = _load_run_list(
        _run_command(
            (str(executable), "runtime", "runs", "list", "--json"),
            workspace,
            fault_environment,
        )
    )
    if document.get("run_count") != 1 or len(runs) != 1:
        raise VerificationFailure
    run = runs[0]
    if (
        run.get("session_id") != CLEANUP_RUNTIME_SESSION
        or run.get("result") != "cleanup_failed"
        or run.get("stop_reason") != "cleanup_failure"
        or not _is_canonical_timestamp(run.get("ended_at"))
    ):
        raise VerificationFailure
    return trace


def _load_cleanup_fault_trace(path: Path) -> _CleanupFaultTrace:
    try:
        raw: object = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise VerificationFailure from error
    if not isinstance(raw, dict):
        raise VerificationFailure
    document = cast(dict[object, object], raw)
    if set(document) != {
        "cleanup_calls",
        "persist_calls",
        "session_cleanup_calls",
    }:
        raise VerificationFailure
    cleanup_calls = document["cleanup_calls"]
    session_cleanup_calls = document["session_cleanup_calls"]
    persist_calls = document["persist_calls"]
    if (
        not isinstance(cleanup_calls, list)
        or not all(isinstance(value, str) for value in cleanup_calls)
        or not isinstance(session_cleanup_calls, list)
        or not all(type(value) is bool for value in session_cleanup_calls)
        or type(persist_calls) is not int
    ):
        raise VerificationFailure
    return _CleanupFaultTrace(
        cleanup_calls=tuple(cast(list[str], cleanup_calls)),
        session_cleanup_calls=tuple(cast(list[bool], session_cleanup_calls)),
        persist_calls=persist_calls,
    )


def _require_bounded_exact_result(
    command: Sequence[str],
    *,
    workspace: Path,
    environment: Mapping[str, str],
    returncode: int,
    stdout: bytes,
    stderr: bytes,
) -> None:
    result = _run_command(
        command,
        workspace,
        environment,
        timeout_seconds=_FAULT_TIMEOUT_SECONDS,
    )
    _require_exact_result(
        result,
        returncode=returncode,
        stdout=stdout,
        stderr=stderr,
    )


def _tree_snapshot(root: Path) -> tuple[tuple[str, int, str, bytes], ...]:
    if not root.exists() and not root.is_symlink():
        return ()
    base = root.parent
    pending = [root]
    snapshot: list[tuple[str, int, str, bytes]] = []
    while pending:
        path = pending.pop()
        metadata = path.lstat()
        relative = str(path.relative_to(base))
        mode = stat.S_IMODE(metadata.st_mode)
        if stat.S_ISLNK(metadata.st_mode):
            snapshot.append((relative, mode, "symlink", os.readlink(path).encode()))
        elif stat.S_ISDIR(metadata.st_mode):
            snapshot.append((relative, mode, "directory", b""))
            pending.extend(sorted(path.iterdir(), reverse=True))
        elif stat.S_ISREG(metadata.st_mode):
            snapshot.append((relative, mode, "file", path.read_bytes()))
        else:
            snapshot.append((relative, mode, "other", b""))
    return tuple(sorted(snapshot))


def _verify_sanitized_product_outputs(*, forbidden_paths: Sequence[Path]) -> None:
    if _product_evidence is None or not _product_evidence:
        raise VerificationFailure
    absolute_path = re.compile(rb"(?:^|[ =:\"'])/(?:[^\s\"']+)")
    pid = re.compile(rb"\bpid(?:=|:|\s)+\d+\b", re.IGNORECASE)
    memory_address = re.compile(rb"\b0x[0-9a-f]+\b", re.IGNORECASE)
    forbidden = (
        b"traceback",
        b"credential",
        b"password",
        b"secret",
        b"sqlite",
        b"backend",
        b"transport identifier",
        b"device identifier",
        b"transport=",
        b"device=",
        b"schema_version:",
        b"resources:",
        b'{"command"',
    )
    path_values = tuple(str(path).encode() for path in forbidden_paths)
    for output in _product_evidence:
        lowered = output.lower()
        if (
            any(value in lowered for value in forbidden)
            or any(path in output for path in path_values)
            or absolute_path.search(output) is not None
            or pid.search(output) is not None
            or memory_address.search(output) is not None
        ):
            raise VerificationFailure


def _verify_two_run_persistence(
    executable: Path,
    *,
    first_run: str,
    second_run: str,
    workspace: Path,
    environment: Mapping[str, str],
) -> None:
    document = _load_canonical_json_result(
        _run_command(
            (str(executable), "runtime", "runs", "list", "--json"),
            workspace,
            environment,
        )
    )
    raw_runs_value = document.get("runs")
    if not isinstance(raw_runs_value, list) or document.get("run_count") != 2:
        raise VerificationFailure
    raw_runs = cast(list[object], raw_runs_value)
    runs = [cast(dict[str, object], run) for run in raw_runs if isinstance(run, dict)]
    if len(runs) != len(raw_runs) or [run.get("run_id") for run in runs] != [
        second_run,
        first_run,
    ]:
        raise VerificationFailure
    if any(run.get("result") != "completed" for run in runs):
        raise VerificationFailure


def _verify_event_queries(
    executable: Path,
    run_id: str,
    expected_events: list[dict[str, object]],
    *,
    workspace: Path,
    environment: Mapping[str, str],
) -> None:
    text = _require_success(
        _run_command(
            (str(executable), "runtime", "events", "--run", run_id),
            workspace,
            environment,
        ),
        environment_sensitive=False,
    )
    if text.stderr or text.stdout != _render_event_page(run_id, expected_events):
        raise VerificationFailure
    after = _load_event_page(
        _run_command(
            (
                str(executable),
                "runtime",
                "events",
                "--run",
                run_id,
                "--after",
                "3",
                "--json",
            ),
            workspace,
            environment,
        ),
        run_id=run_id,
    )
    limited = _load_event_page(
        _run_command(
            (
                str(executable),
                "runtime",
                "events",
                "--run",
                run_id,
                "--limit",
                "1",
                "--json",
            ),
            workspace,
            environment,
        ),
        run_id=run_id,
    )
    maximum = _load_event_page(
        _run_command(
            (
                str(executable),
                "runtime",
                "events",
                "--run",
                run_id,
                "--limit",
                "1000",
                "--json",
            ),
            workspace,
            environment,
        ),
        run_id=run_id,
    )
    if after != expected_events[4:] or limited != expected_events[:1] or maximum != expected_events:
        raise VerificationFailure


def _verify_prune(
    executable: Path,
    *,
    removed_run: str,
    retained_run: str,
    retained_events: list[dict[str, object]],
    workspace: Path,
    environment: Mapping[str, str],
) -> None:
    _require_exact_result(
        _run_command(
            (str(executable), "runtime", "runs", "prune", "--keep", "1"),
            workspace,
            environment,
        ),
        returncode=SUCCESS,
        stdout=b"deleted-runs=1\n",
        stderr=b"",
    )
    for arguments in (
        ("runtime", "runs", "show", removed_run),
        ("runtime", "events", "--run", removed_run),
    ):
        _require_exact_result(
            _run_command((str(executable), *arguments), workspace, environment),
            returncode=11,
            stdout=b"",
            stderr=_RUN_NOT_FOUND,
        )
    _verify_run_queryable(
        executable,
        retained_run,
        expected_result="completed",
        workspace=workspace,
        environment=environment,
    )
    events = _load_event_page(
        _run_command(
            (str(executable), "runtime", "events", "--run", retained_run, "--json"),
            workspace,
            environment,
        ),
        run_id=retained_run,
    )
    if events != retained_events:
        raise VerificationFailure


def _verify_b1_active_safe_prune(
    executable: Path,
    *,
    removed_run: str,
    retained_finalized_run: str,
    retained_finalized_events: list[dict[str, object]],
    active_runs: Sequence[tuple[str, str]],
    workspace: Path,
    environment: Mapping[str, str],
) -> None:
    if len(active_runs) != 2:
        raise VerificationFailure
    _verify_prune(
        executable,
        removed_run=removed_run,
        retained_run=retained_finalized_run,
        retained_events=retained_finalized_events,
        workspace=workspace,
        environment=environment,
    )
    _verify_b1_pruned_run_listing(
        executable,
        retained_finalized_run=retained_finalized_run,
        active_runs=active_runs,
        workspace=workspace,
        environment=environment,
    )
    observed: list[str] = []
    for session, expected_run in active_runs:
        active_run = _verify_active_runtime(
            executable,
            session=session,
            workspace=workspace,
            environment=environment,
        )
        if active_run != expected_run:
            raise VerificationFailure
        observed.append(active_run)
    _assert_distinct_canonical_run_ids((removed_run, retained_finalized_run, *observed))


def _verify_b1_pruned_run_listing(
    executable: Path,
    *,
    retained_finalized_run: str,
    active_runs: Sequence[tuple[str, str]],
    workspace: Path,
    environment: Mapping[str, str],
) -> None:
    _document, runs = _load_run_list(
        _run_command(
            (str(executable), "runtime", "runs", "list", "--json"),
            workspace,
            environment,
        )
    )
    expected_active = {run_id: session for session, run_id in active_runs}
    expected_ids = {retained_finalized_run, *expected_active}
    if len(runs) != len(expected_ids):
        raise VerificationFailure
    if {run.get("run_id") for run in runs} != expected_ids:
        raise VerificationFailure
    for run in runs:
        run_id = run.get("run_id")
        if run_id == retained_finalized_run:
            if run.get("result") != "completed":
                raise VerificationFailure
        elif (
            not isinstance(run_id, str)
            or run.get("session_id") != expected_active.get(run_id)
            or run.get("result") is not None
            or run.get("ended_at") is not None
            or run.get("event_high_water_mark") != 3
        ):
            raise VerificationFailure


def _verify_b1_final_history(
    executable: Path,
    *,
    removed_run: str,
    retained_runs: Sequence[str],
    workspace: Path,
    environment: Mapping[str, str],
) -> None:
    document, runs = _load_run_list(
        _run_command(
            (str(executable), "runtime", "runs", "list", "--json"),
            workspace,
            environment,
        )
    )
    if document.get("run_count") != len(retained_runs):
        raise VerificationFailure
    if {run.get("run_id") for run in runs} != set(retained_runs):
        raise VerificationFailure
    if removed_run in {run.get("run_id") for run in runs}:
        raise VerificationFailure
    if any(
        run.get("result") != "completed"
        or run.get("stop_reason") != "cli_stop"
        or not isinstance(run.get("ended_at"), str)
        or run.get("event_high_water_mark") != 11
        for run in runs
    ):
        raise VerificationFailure
    ordering: list[tuple[str, str]] = []
    for run in runs:
        started_at = run.get("started_at")
        run_id = run.get("run_id")
        if not isinstance(started_at, str) or not isinstance(run_id, str):
            raise VerificationFailure
        ordering.append((started_at, run_id))
    if ordering != sorted(ordering, reverse=True):
        raise VerificationFailure
    _assert_distinct_canonical_run_ids(tuple(retained_runs))


def _load_run_list(
    result: CommandResult,
) -> tuple[dict[str, object], list[dict[str, object]]]:
    document = _load_canonical_json_result(result)
    raw_runs_value = document.get("runs")
    if not isinstance(raw_runs_value, list):
        raise VerificationFailure
    raw_runs = cast(list[object], raw_runs_value)
    if document.get("run_count") != len(raw_runs):
        raise VerificationFailure
    runs = [cast(dict[str, object], run) for run in raw_runs if isinstance(run, dict)]
    if len(runs) != len(raw_runs):
        raise VerificationFailure
    return document, runs


def _assert_distinct_canonical_run_ids(run_ids: Sequence[str]) -> None:
    if len(run_ids) != len(set(run_ids)):
        raise VerificationFailure
    try:
        parsed = tuple(uuid.UUID(run_id) for run_id in run_ids)
    except (ValueError, AttributeError) as error:
        raise VerificationFailure from error
    if any(
        value.version != 4 or str(value) != run_id
        for value, run_id in zip(parsed, run_ids, strict=True)
    ):
        raise VerificationFailure


def _assert_exact_success_events(events: Sequence[dict[str, object]], *, count: int) -> None:
    if count not in {4, 12} or len(events) != count:
        raise VerificationFailure
    if [event.get("sequence") for event in events] != list(range(count)):
        raise VerificationFailure
    summaries = [
        (event.get("event_type"), event.get("outcome"), event.get("summary")) for event in events
    ]
    if summaries != list(_SUCCESS_EVENT_SEQUENCE[:count]):
        raise VerificationFailure


def _load_canonical_json_result(result: CommandResult) -> dict[str, object]:
    successful = _require_success(result, environment_sensitive=False)
    if successful.stderr or not successful.stdout.endswith(b"\n"):
        raise VerificationFailure
    try:
        decoded = successful.stdout.decode("ascii")
        raw_document: object = json.loads(decoded)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise VerificationFailure from error
    if not isinstance(raw_document, dict):
        raise VerificationFailure
    document = cast(dict[str, object], raw_document)
    canonical = (
        json.dumps(document, ensure_ascii=True, separators=(",", ":"), sort_keys=True) + "\n"
    ).encode("ascii")
    if canonical != successful.stdout:
        raise VerificationFailure
    return document


def _load_event_page(result: CommandResult, *, run_id: str) -> list[dict[str, object]]:
    document = _load_canonical_json_result(result)
    raw_events_value = document.get("events")
    if document.get("run_id") != run_id or not isinstance(raw_events_value, list):
        raise VerificationFailure
    raw_events = cast(list[object], raw_events_value)
    if document.get("event_count") != len(raw_events):
        raise VerificationFailure
    validated: list[dict[str, object]] = []
    previous: int | None = None
    for raw_event in raw_events:
        if not isinstance(raw_event, dict):
            raise VerificationFailure
        event = cast(dict[str, object], raw_event)
        if event.get("run_id") != run_id:
            raise VerificationFailure
        sequence = event.get("sequence")
        summary = event.get("summary")
        event_type = event.get("event_type")
        outcome = event.get("outcome")
        if (
            type(sequence) is not int
            or (previous is not None and sequence != previous + 1)
            or not isinstance(summary, str)
            or any(ord(character) < 32 or ord(character) > 126 for character in summary)
            or (event_type, outcome, summary) not in _SUCCESS_EVENT_SUMMARIES
        ):
            raise VerificationFailure
        previous = sequence
        validated.append(event)
    return validated


def _render_event_page(run_id: str, events: list[dict[str, object]]) -> bytes:
    lines = [f"run={run_id}", f"event-count={len(events)}"]
    for event in events:
        lines.append(
            f"event={event['sequence']} type={event['event_type']} "
            f"outcome={event['outcome']} severity={event['severity']} "
            f"resource={event['resource_identity'] or 'none'} "
            f"lifecycle={event['lifecycle_state'] or 'none'} "
            f"health={event['health_status'] or 'none'} "
            f"recorded-at={event['recorded_at']} summary={event['summary']}"
        )
    return ("\n".join(lines) + "\n").encode("ascii")


def _require_exact_result(
    result: CommandResult,
    *,
    returncode: int,
    stdout: bytes,
    stderr: bytes,
) -> None:
    if result.returncode != returncode or result.stdout != stdout or result.stderr != stderr:
        raise VerificationFailure


def _short_temporary_parent() -> Path:
    parent = Path(tempfile.gettempdir()).resolve()
    if not parent.is_absolute() or not parent.is_dir():
        raise VerificationEnvironmentBlocked
    return parent


def _assert_short_control_path(state_root: Path, session: str) -> None:
    socket_path = state_root / session / "control.sock"
    if len(os.fsencode(socket_path)) > _MAX_UNIX_SOCKET_PATH_BYTES:
        raise VerificationEnvironmentBlocked


def _cleanup_owner(
    owner: subprocess.Popen[bytes],
    executable: Path,
    *,
    session: str,
    workspace: Path,
    environment: Mapping[str, str],
) -> None:
    if owner.poll() is not None:
        return
    primary_error: BaseException | None = None
    try:
        subprocess.run(
            (str(executable), "runtime", "stop", "--session", session),
            cwd=workspace,
            env=environment,
            capture_output=True,
            check=False,
            timeout=_CLEANUP_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.TimeoutExpired):
        pass
    except BaseException as error:
        primary_error = error
    cleanup_error: VerificationFailure | None = None
    try:
        owner.wait(timeout=_CLEANUP_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired:
        owner.terminate()
        try:
            owner.wait(timeout=_CLEANUP_TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired:
            owner.kill()
            try:
                owner.wait(timeout=_CLEANUP_TIMEOUT_SECONDS)
            except (OSError, subprocess.TimeoutExpired):
                cleanup_error = VerificationFailure()
    if primary_error is not None:
        raise primary_error
    if cleanup_error is not None:
        raise cleanup_error


def _cleanup_registered_owners(
    owners: list[tuple[subprocess.Popen[bytes], str]],
    executable: Path,
    *,
    workspace: Path,
    environment: Mapping[str, str],
) -> BaseException | None:
    first_error: BaseException | None = None
    for owner, session in reversed(tuple(owners)):
        try:
            _cleanup_owner(
                owner,
                executable,
                session=session,
                workspace=workspace,
                environment=environment,
            )
        except BaseException as error:
            if first_error is None:
                first_error = error
        finally:
            if owner.poll() is not None:
                owners.remove((owner, session))
    return first_error


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
        environment_sensitive=False,
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
        environment_sensitive=False,
    )
    if status.stdout != EXPECTED_RUNTIME_STATUS or status.stderr:
        raise VerificationFailure
    stopped = _require_success(
        runner(
            (str(executable), "runtime", "stop", "--session", RUNTIME_SESSION),
            workspace,
            runtime_environment,
        ),
        environment_sensitive=False,
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
    try:
        relative = resolved.relative_to(environment)
    except ValueError as error:
        raise VerificationFailure from error
    if "site-packages" not in relative.parts:
        raise VerificationFailure


def assert_scaffold_layout(scaffold_path: Path) -> None:
    """Require the installed CLI to render the complete bounded scaffold."""
    if not scaffold_path.is_dir():
        raise VerificationFailure
    actual = tuple(
        sorted(
            path.relative_to(scaffold_path) for path in scaffold_path.rglob("*") if path.is_file()
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
            metadata_names = tuple(name for name in names if name.endswith(".dist-info/METADATA"))
            license_names = tuple(
                name for name in names if name.endswith(".dist-info/licenses/LICENSE")
            )
            if len(metadata_names) != 1 or len(license_names) != 1:
                raise VerificationFailure
            metadata = BytesParser(policy=default).parsebytes(archive.read(metadata_names[0]))
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
    *,
    timeout_seconds: float = 180.0,
) -> CommandResult:
    try:
        completed = subprocess.run(
            command,
            cwd=cwd,
            env=environment,
            capture_output=True,
            check=False,
            timeout=timeout_seconds,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise VerificationFailure from error
    result = CommandResult(completed.returncode, completed.stdout, completed.stderr)
    if Path(command[0]).name in {"hiyelx", "hiyelx.exe"}:
        _record_product_output(result.stdout, result.stderr)
    return result


def _record_product_output(*values: bytes) -> None:
    if _product_evidence is not None:
        _product_evidence.extend(value for value in values if value)


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
            raise VerificationFailure
        pending.extend(chunk)
    _record_product_output(*(line + b"\n" for line in lines))
    return tuple(lines)


def _require_success(
    result: CommandResult,
    *,
    environment_sensitive: bool,
) -> CommandResult:
    if result.returncode == SUCCESS:
        return result
    if environment_sensitive and _looks_dependency_environment_blocked(result.stderr):
        raise VerificationEnvironmentBlocked
    raise VerificationFailure


def _looks_dependency_environment_blocked(stderr: bytes) -> bool:
    lowered = stderr.lower()
    indicators = (
        b"could not resolve host",
        b"temporary failure in name resolution",
        b"name or service not known",
        b"failed to lookup address information",
        b"network is unreachable",
        b"dns error",
        b"no interpreter found for python 3.12",
        b"python 3.12 is not installed",
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
