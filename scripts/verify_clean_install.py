"""Build and verify the installed HIYELX wheel outside the source checkout."""

from __future__ import annotations

import json
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
HISTORY_SUCCESS_MARKERS = (
    "history-missing-store=passed",
    "history-active-query=passed",
    "history-post-stop-query=passed",
    "history-cross-process-persistence=passed",
    "history-events-cursor-json=passed",
    "history-prune=passed",
    "history-artifact-cleanup=passed",
)
_RUN_NOT_FOUND = b"error: runtime run is not found\n"
_SUCCESS_EVENT_SUMMARIES = frozenset(
    {
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
    }
)
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
    """Prove the complete RTO-3 journey through the installed wheel CLI."""
    if sys.platform not in {"darwin", "linux"}:
        raise VerificationEnvironmentBlocked
    state_parent = _short_temporary_parent()
    with tempfile.TemporaryDirectory(
        prefix="hxctl-",
        dir=state_parent,
    ) as state_name:
        runtime_environment = dict(environment)
        runtime_environment["HIYELX_RUNTIME_STATE_DIR"] = state_name
        history_root = workspace / "history"
        runtime_environment["HIYELX_RUNTIME_HISTORY_DIR"] = str(history_root)
        _assert_short_control_path(Path(state_name), SECOND_RUNTIME_SESSION)
        owners: list[tuple[subprocess.Popen[bytes], str]] = []
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
            )
            owners.append((first_owner, RUNTIME_SESSION))
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
            )
            owners.append((second_owner, SECOND_RUNTIME_SESSION))
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
            _verify_prune(
                executable,
                removed_run=first_run,
                retained_run=second_run,
                retained_events=second_events,
                workspace=workspace,
                environment=runtime_environment,
            )
            if len(first_events) != len(second_events):
                raise VerificationFailure
        except (OSError, subprocess.TimeoutExpired) as error:
            raise VerificationFailure from error
        finally:
            for owner, session in reversed(owners):
                _cleanup_owner(
                    owner,
                    executable,
                    session=session,
                    workspace=workspace,
                    environment=runtime_environment,
                )
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
    expected = (f"session={session}".encode(), b"runtime=running", b"control=ready")
    try:
        if _read_owner_lines(owner, len(expected)) != expected:
            raise VerificationFailure
    except BaseException:
        _cleanup_owner(
            owner,
            executable,
            session=session,
            workspace=workspace,
            environment=environment,
        )
        raise
    return owner


def _verify_active_runtime(
    executable: Path,
    *,
    session: str,
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
    matching = [run for run in runs if run.get("session_id") == session]
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
    if [event["sequence"] for event in events] != list(range(4)):
        raise VerificationFailure
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
        remaining_stdout, remaining_stderr = owner.communicate(
            timeout=_OWNER_EXIT_TIMEOUT_SECONDS
        )
    except subprocess.TimeoutExpired as error:
        _cleanup_owner(
            owner,
            executable,
            session=session,
            workspace=workspace,
            environment=environment,
        )
        raise VerificationFailure from error
    if (
        owner.returncode != SUCCESS
        or remaining_stdout != b"runtime=stopped\n"
        or remaining_stderr
        or (state_root / session).exists()
    ):
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
    if [event["sequence"] for event in events] != list(range(12)):
        raise VerificationFailure
    return events


def _verify_run_queryable(
    executable: Path,
    run_id: str,
    *,
    expected_result: str,
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
        json.dumps(document, ensure_ascii=True, separators=(",", ":"), sort_keys=True)
        + "\n"
    ).encode("ascii")
    if canonical != successful.stdout:
        raise VerificationFailure
    return document


def _load_event_page(result: CommandResult, *, run_id: str) -> list[dict[str, object]]:
    document = _load_canonical_json_result(result)
    raw_events_value = document.get("events")
    if (
        document.get("run_id") != run_id
        or not isinstance(raw_events_value, list)
    ):
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
    if (
        result.returncode != returncode
        or result.stdout != stdout
        or result.stderr != stderr
    ):
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
    except (OSError, subprocess.TimeoutExpired) as error:
        raise VerificationFailure from error
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
