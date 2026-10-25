import json
import os
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import time
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import cast
from zipfile import ZipFile

import pytest

from scripts import verify_clean_install as verify

REPOSITORY_ROOT = Path(__file__).parents[2]


class FakeRunner:
    def __init__(self, expected: bytes, *, fail_demo: bool = False) -> None:
        self.expected = expected
        self.fail_demo = fail_demo
        self.commands: list[tuple[str, ...]] = []

    def __call__(
        self,
        command: Sequence[str],
        cwd: Path,
        environment: Mapping[str, str],
    ) -> verify.CommandResult:
        self.commands.append(tuple(command))
        assert cwd != REPOSITORY_ROOT
        assert "PYTHONPATH" not in environment
        assert "VIRTUAL_ENV" not in environment

        if "build" in command:
            output = Path(command[command.index("--out-dir") + 1])
            output.mkdir(parents=True)
            write_test_wheel(output / "hiyelx-0.2.0a1-py3-none-any.whl")
        elif "venv" in command:
            environment_path = Path(command[-1])
            binaries = environment_path / "bin"
            binaries.mkdir(parents=True)
            (binaries / "python").write_text("", encoding="utf-8")
            (binaries / "hiyelx").write_text("", encoding="utf-8")
        elif "-c" in command:
            environment_path = Path(command[0]).parents[1]
            installed = environment_path / "lib/python3.12/site-packages/hiyelx/__init__.py"
            installed.parent.mkdir(parents=True)
            installed.write_text("", encoding="utf-8")
            return verify.CommandResult(0, f"{installed}\n".encode(), b"")
        elif command[-1] == "--version":
            return verify.CommandResult(0, b"Python 3.12.14\n", b"")
        elif "validate-config" in command:
            return verify.CommandResult(0, b"configuration=valid\n", b"")
        elif "scaffold" in command:
            scaffold_path = Path(command[3])
            for relative_path in verify.EXPECTED_SCAFFOLD_FILES:
                destination = scaffold_path / relative_path
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_text("generated", encoding="utf-8")
            return verify.CommandResult(
                0,
                b"scaffold=motor-driver\n"
                b"package=acme_motor_driver\n"
                b"model=motor.acme.reference\n"
                b"files=6\n",
                b"",
            )
        elif command[-2:] == ("demo", "sim-motor"):
            if self.fail_demo:
                return verify.CommandResult(1, b"", b"secret backend failure")
            return verify.CommandResult(0, self.expected, b"")
        elif "runtime" in command:
            assert environment["HIYELX_RUNTIME_STATE_DIR"] == str(cwd / "runtime-state")
            runtime_index = command.index("runtime")
            runtime_command = command[runtime_index + 1]
            if runtime_command == "start":
                return verify.CommandResult(
                    0,
                    b"\n".join(verify.EXPECTED_RUNTIME_READY) + b"\nruntime=stopped\n",
                    b"",
                )
            if runtime_command == "status":
                return verify.CommandResult(0, verify.EXPECTED_RUNTIME_STATUS, b"")
            if runtime_command == "stop":
                return verify.CommandResult(0, verify.EXPECTED_RUNTIME_STOP, b"")
        return verify.CommandResult(0, b"", b"")


class FakeLifecycleOwner:
    def __init__(
        self,
        trace: list[str],
        *,
        pid: int,
        cleanup_path: Path | None = None,
    ) -> None:
        self.trace = trace
        self.pid = pid
        self.returncode: int | None = None
        self._stdout = b""
        self._stderr = b""
        self._cleanup_path = cleanup_path

    def send_signal(self, sent_signal: int) -> None:
        assert sent_signal == signal.SIGINT
        self.trace.append("sigint")
        self.returncode = 0
        self._stdout = b"runtime=stopped\n"
        if self._cleanup_path is not None:
            shutil.rmtree(self._cleanup_path)

    def kill(self) -> None:
        self.trace.append("kill")
        self.returncode = -signal.SIGKILL

    def communicate(self, timeout: float | None = None) -> tuple[bytes, bytes]:
        assert timeout == verify._OWNER_EXIT_TIMEOUT_SECONDS  # pyright: ignore[reportPrivateUsage]
        if self.returncode is None:
            raise subprocess.TimeoutExpired(
                cmd=("hiyelx",),
                timeout=verify._OWNER_EXIT_TIMEOUT_SECONDS,  # pyright: ignore[reportPrivateUsage]
            )
        return self._stdout, self._stderr

    def poll(self) -> int | None:
        return self.returncode


_RUN_ONE = "10000000-0000-4000-8000-000000000001"
_RUN_TWO = "20000000-0000-4000-8000-000000000002"
_RUN_THREE = "30000000-0000-4000-8000-000000000003"
_RUN_FOUR = "40000000-0000-4000-8000-000000000004"


def _canonical(document: object) -> verify.CommandResult:
    return verify.CommandResult(
        0,
        (
            json.dumps(document, ensure_ascii=True, separators=(",", ":"), sort_keys=True) + "\n"
        ).encode("ascii"),
        b"",
    )


def _run_document(
    run_id: str,
    *,
    session: str,
    result: str | None,
    high_water_mark: int,
    started_at: str = "2026-10-19T10:00:00.000000Z",
) -> dict[str, object]:
    return {
        "ended_at": None if result is None else "2026-10-19T10:00:01.000000Z",
        "event_high_water_mark": high_water_mark,
        "result": result,
        "run_id": run_id,
        "session_id": session,
        "started_at": started_at,
        "stop_reason": None if result is None else "cli_stop",
    }


def _event_documents(run_id: str) -> list[dict[str, object]]:
    values = (
        ("runtime_start", "requested", "runtime start requested", None, None, None),
        (
            "resource_start",
            "attempted",
            "resource start attempted",
            "sim_motor",
            "created",
            "healthy",
        ),
        (
            "resource_start",
            "succeeded",
            "resource start succeeded",
            "sim_motor",
            "running",
            "healthy",
        ),
        ("runtime_running", "succeeded", "runtime running", None, None, None),
        ("safe_stop", "requested", "safe-stop requested", None, None, None),
        (
            "safe_stop",
            "attempted",
            "motor safe-stop attempted",
            "sim_motor",
            "running",
            "healthy",
        ),
        (
            "safe_stop",
            "succeeded",
            "motor safe-stop succeeded",
            "sim_motor",
            "running",
            "healthy",
        ),
        (
            "safe_stop_cleanup",
            "completed",
            "safe-stop cleanup completed",
            None,
            None,
            None,
        ),
        (
            "runtime_shutdown",
            "requested",
            "runtime shutdown requested",
            None,
            None,
            None,
        ),
        (
            "resource_shutdown",
            "attempted",
            "resource shutdown attempted",
            "sim_motor",
            "running",
            "healthy",
        ),
        (
            "resource_shutdown",
            "succeeded",
            "resource shutdown succeeded",
            "sim_motor",
            "stopped",
            "healthy",
        ),
        ("runtime_stopped", "succeeded", "runtime stopped", None, None, None),
    )
    return [
        {
            "event_type": event_type,
            "health_status": health,
            "lifecycle_state": lifecycle,
            "outcome": outcome,
            "recorded_at": f"2026-10-19T10:00:{sequence:02d}.000000Z",
            "resource_identity": resource,
            "run_id": run_id,
            "schema_version": 1,
            "sequence": sequence,
            "severity": "info",
            "summary": summary,
        }
        for sequence, (event_type, outcome, summary, resource, lifecycle, health) in enumerate(
            values
        )
    ]


def _event_page(run_id: str, events: list[dict[str, object]]) -> verify.CommandResult:
    return _canonical({"event_count": len(events), "events": events, "run_id": run_id})


def _script_results(
    monkeypatch: pytest.MonkeyPatch,
    results: Sequence[verify.CommandResult],
) -> list[tuple[str, ...]]:
    pending = list(results)
    commands: list[tuple[str, ...]] = []

    def run(
        command: Sequence[str],
        _cwd: Path,
        _environment: Mapping[str, str],
    ) -> verify.CommandResult:
        commands.append(tuple(command))
        if not pending:
            raise AssertionError("unexpected verifier command")
        return pending.pop(0)

    monkeypatch.setattr(verify, "_run_command", run)
    return commands


def write_test_wheel(
    path: Path,
    *,
    license_expression: str = verify.EXPECTED_LICENSE_EXPRESSION,
    include_license: bool = True,
) -> None:
    with ZipFile(path, "w") as wheel:
        wheel.writestr(
            "hiyelx-0.2.0a1.dist-info/METADATA",
            "Metadata-Version: 2.4\n"
            "Name: hiyelx\n"
            "Version: 0.2.0a1\n"
            f"License-Expression: {license_expression}\n"
            "License-File: LICENSE\n\n",
        )
        if include_license:
            wheel.write(
                REPOSITORY_ROOT / "LICENSE",
                "hiyelx-0.2.0a1.dist-info/licenses/LICENSE",
            )


def test_canonical_transcript_loading_and_equality() -> None:
    expected_path = REPOSITORY_ROOT / "examples/expected/sim-motor.txt"
    expected = expected_path.read_bytes()

    assert len(verify.load_expected_transcript(expected_path)) == 14
    verify.assert_transcript_equal(expected, expected.rstrip(b"\n"))


def test_transcript_drift_is_rejected() -> None:
    with pytest.raises(verify.VerificationFailure):
        verify.assert_transcript_equal(b"expected\n", b"drifted\n")


def test_source_checkout_import_is_rejected(tmp_path: Path) -> None:
    environment = tmp_path / "venv"
    with pytest.raises(verify.VerificationFailure):
        verify.assert_installed_package_path(
            str(REPOSITORY_ROOT / "src/hiyelx/__init__.py"),
            repository_root=REPOSITORY_ROOT,
            environment_path=environment,
        )


def test_clean_environment_non_site_packages_import_is_rejected(tmp_path: Path) -> None:
    environment = tmp_path / "venv"
    imported = environment / "src/hiyelx/__init__.py"
    with pytest.raises(verify.VerificationFailure):
        verify.assert_installed_package_path(
            str(imported),
            repository_root=REPOSITORY_ROOT,
            environment_path=environment,
        )


def test_scaffold_layout_drift_is_rejected(tmp_path: Path) -> None:
    scaffold = tmp_path / "scaffold"
    scaffold.mkdir()
    (scaffold / "README.md").write_text("incomplete", encoding="utf-8")

    with pytest.raises(verify.VerificationFailure):
        verify.assert_scaffold_layout(scaffold)


def test_wheel_license_metadata_drift_is_rejected(tmp_path: Path) -> None:
    wheel = tmp_path / "hiyelx-0.2.0a1-py3-none-any.whl"
    write_test_wheel(wheel, license_expression="MIT")

    with pytest.raises(verify.VerificationFailure):
        verify.assert_wheel_license(wheel, repository_root=REPOSITORY_ROOT)


def test_missing_wheel_license_file_is_rejected(tmp_path: Path) -> None:
    wheel = tmp_path / "hiyelx-0.2.0a1-py3-none-any.whl"
    write_test_wheel(wheel, include_license=False)

    with pytest.raises(verify.VerificationFailure):
        verify.assert_wheel_license(wheel, repository_root=REPOSITORY_ROOT)


def test_verification_output_is_sanitized(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail() -> str:
        raise RuntimeError("credential=top-secret /private/tmp/hidden")

    monkeypatch.setattr(verify, "run_clean_install_verification", fail)
    assert verify.main() == verify.FAILURE
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "error: clean-install verification failed\n"
    assert "top-secret" not in captured.err
    assert "/private/tmp" not in captured.err


def test_environment_blocked_output_is_sanitized(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def blocked() -> str:
        raise verify.VerificationEnvironmentBlocked("secret index URL")

    monkeypatch.setattr(verify, "run_clean_install_verification", blocked)
    assert verify.main() == verify.ENVIRONMENT_BLOCKED
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == (
        "blocked: clean-install verification requires package access and loopback support\n"
    )
    assert "secret" not in captured.err


def test_keyboard_interrupt_output_is_sanitized_after_cleanup(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(verify, "_CLEANUP_TIMEOUT_SECONDS", 0.1)
    workspace = tmp_path / "private-workspace"
    owners: list[subprocess.Popen[bytes]] = []

    def interrupt() -> str:
        workspace.mkdir()
        owner = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(30)"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        owners.append(owner)
        try:
            raise KeyboardInterrupt("credential /private/task/path")
        finally:
            verify._cleanup_owner(  # pyright: ignore[reportPrivateUsage]
                owner,
                workspace / "missing-hiyelx",
                session=verify.RUNTIME_SESSION,
                workspace=workspace,
                environment=dict(os.environ),
            )
            shutil.rmtree(workspace)

    monkeypatch.setattr(verify, "run_clean_install_verification", interrupt)
    assert verify.main() == verify.FAILURE
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "error: clean-install verification interrupted\n"
    assert "Traceback" not in captured.err
    assert "credential" not in captured.err
    assert "/private" not in captured.err
    assert not any(marker in captured.err for marker in verify.HISTORY_SUCCESS_MARKERS)
    assert len(owners) == 1 and owners[0].poll() is not None
    assert not workspace.exists()


def test_main_does_not_swallow_other_base_exceptions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def abort() -> str:
        raise SystemExit(7)

    monkeypatch.setattr(verify, "run_clean_install_verification", abort)
    with pytest.raises(SystemExit, match="7"):
        verify.main()


def test_success_markers_are_emitted_in_contract_order(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        verify,
        "run_clean_install_verification",
        lambda: "hiyelx-0.2.0a1-py3-none-any.whl",
    )

    assert verify.main() == verify.SUCCESS

    captured = capsys.readouterr()
    assert captured.err == ""
    output_lines = captured.out.splitlines()
    assert len(output_lines) == 29
    assert output_lines == [
        "wheel=hiyelx-0.2.0a1-py3-none-any.whl",
        *verify.HISTORY_SUCCESS_MARKERS,
        "clean-install=passed",
        *verify._RTO4_VERIFICATION_SUCCESS_MARKERS,  # pyright: ignore[reportPrivateUsage]
        *verify._SIM_PREVIEW_SUCCESS_MARKERS,  # pyright: ignore[reportPrivateUsage]
    ]
    assert len(verify._RTO4_VERIFICATION_SUCCESS_MARKERS) == len(  # pyright: ignore[reportPrivateUsage]
        set(verify._RTO4_VERIFICATION_SUCCESS_MARKERS)  # pyright: ignore[reportPrivateUsage]
    )
    assert verify._RTO4_VERIFICATION_SUCCESS_MARKERS == (  # pyright: ignore[reportPrivateUsage]
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
    assert verify._SIM_PREVIEW_SUCCESS_MARKERS == (  # pyright: ignore[reportPrivateUsage]
        "sim-preview-wheel=passed",
        "sim-preview-source-isolation=passed",
        "sim-preview-active=passed",
        "sim-preview-repeat=passed",
        "sim-preview-negative=passed",
        "sim-preview-disconnect=passed",
        "sim-preview-cleanup=passed",
        "sim-preview-acceptance=passed",
    )
    assert len(verify._SIM_PREVIEW_SUCCESS_MARKERS) == len(  # pyright: ignore[reportPrivateUsage]
        set(verify._SIM_PREVIEW_SUCCESS_MARKERS)  # pyright: ignore[reportPrivateUsage]
    )
    assert output_lines[-1] == "sim-preview-acceptance=passed"


def test_partial_failure_emits_no_success_marker(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail() -> str:
        raise verify.VerificationFailure("private journey path")

    monkeypatch.setattr(verify, "run_clean_install_verification", fail)
    assert verify.main() == verify.FAILURE
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "error: clean-install verification failed\n"
    assert not any(marker in captured.err for marker in verify.HISTORY_SUCCESS_MARKERS)
    assert not any(
        marker in captured.err
        for marker in verify._RTO4_VERIFICATION_SUCCESS_MARKERS  # pyright: ignore[reportPrivateUsage]
    )
    assert not any(
        marker in captured.err
        for marker in verify._SIM_PREVIEW_SUCCESS_MARKERS  # pyright: ignore[reportPrivateUsage]
    )
    assert verify._product_evidence is None  # pyright: ignore[reportPrivateUsage]


@pytest.mark.parametrize(
    "result",
    (
        verify.CommandResult(1, b"", b"private failure"),
        verify.CommandResult(0, b"{}\n", b""),
        verify.CommandResult(0, verify.EXPECTED_SIMULATION_PREVIEW, b"private warning"),
    ),
)
def test_installed_preview_result_rejects_noncanonical_or_noisy_output(
    result: verify.CommandResult,
) -> None:
    with pytest.raises(verify.VerificationFailure):
        verify._verify_installed_preview_result(result)  # pyright: ignore[reportPrivateUsage]


def test_installed_preview_result_accepts_exact_canonical_snapshot() -> None:
    assert (
        verify._verify_installed_preview_result(  # pyright: ignore[reportPrivateUsage]
            verify.CommandResult(0, verify.EXPECTED_SIMULATION_PREVIEW, b"")
        )
        == verify.EXPECTED_SIMULATION_PREVIEW
    )


def test_product_evidence_captures_public_cli_but_excludes_build_tools(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    results = iter(
        (
            subprocess.CompletedProcess([], 0, b"configuration=valid\n", b""),
            subprocess.CompletedProcess([], 0, b"build path=/private/task\n", b""),
        )
    )
    observed_timeouts: list[float] = []

    def run(*_args: object, **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        timeout = kwargs.get("timeout")
        assert isinstance(timeout, float)
        observed_timeouts.append(timeout)
        return next(results)

    monkeypatch.setattr(subprocess, "run", run)
    evidence: list[bytes] = []
    monkeypatch.setattr(verify, "_product_evidence", evidence)  # pyright: ignore[reportPrivateUsage]

    verify._run_command(  # pyright: ignore[reportPrivateUsage]
        (str(tmp_path / "hiyelx"), "validate-config", "config.yaml"),
        tmp_path,
        {},
    )
    verify._run_command(("uv", "build"), tmp_path, {})  # pyright: ignore[reportPrivateUsage]

    assert evidence == [b"configuration=valid\n"]
    assert observed_timeouts == [180.0, 180.0]


def test_temporary_workspace_is_removed_after_success(tmp_path: Path) -> None:
    expected = (REPOSITORY_ROOT / "examples/expected/sim-motor.txt").read_bytes()

    wheel = verify.run_clean_install_verification(
        repository_root=REPOSITORY_ROOT,
        runner=FakeRunner(expected),
        temporary_parent=tmp_path,
    )

    assert wheel == "hiyelx-0.2.0a1-py3-none-any.whl"
    assert tuple(tmp_path.iterdir()) == ()


def test_temporary_workspace_is_removed_after_failure(tmp_path: Path) -> None:
    expected = (REPOSITORY_ROOT / "examples/expected/sim-motor.txt").read_bytes()

    with pytest.raises(verify.VerificationFailure):
        verify.run_clean_install_verification(
            repository_root=REPOSITORY_ROOT,
            runner=FakeRunner(expected, fail_demo=True),
            temporary_parent=tmp_path,
        )

    assert tuple(tmp_path.iterdir()) == ()


def test_temporary_workspace_is_removed_after_base_exception(tmp_path: Path) -> None:
    class Abort(BaseException):
        pass

    def abort(
        _command: Sequence[str],
        _cwd: Path,
        _environment: Mapping[str, str],
    ) -> verify.CommandResult:
        raise Abort

    with pytest.raises(Abort):
        verify.run_clean_install_verification(
            repository_root=REPOSITORY_ROOT,
            runner=abort,
            temporary_parent=tmp_path,
        )

    assert tuple(tmp_path.iterdir()) == ()


def test_fake_clean_install_never_invokes_physical_hardware(tmp_path: Path) -> None:
    expected = (REPOSITORY_ROOT / "examples/expected/sim-motor.txt").read_bytes()
    runner = FakeRunner(expected)

    verify.run_clean_install_verification(
        repository_root=REPOSITORY_ROOT,
        runner=runner,
        temporary_parent=tmp_path,
    )

    assert all("hardware" not in command for command in runner.commands)


def test_missing_store_contract_is_mutation_free(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    results = (
        verify.CommandResult(0, b"run-count=0\n", b""),
        verify.CommandResult(11, b"", b"error: runtime run is not found\n"),
        verify.CommandResult(11, b"", b"error: runtime run is not found\n"),
        verify.CommandResult(0, b"deleted-runs=0\n", b""),
    )
    commands = _script_results(monkeypatch, results)
    history = tmp_path / "missing-history"

    verify._verify_missing_history_store(  # pyright: ignore[reportPrivateUsage]
        tmp_path / "hiyelx",
        workspace=tmp_path,
        environment={},
        history_root=history,
    )

    assert not history.exists()
    assert [command[2:] for command in commands] == [
        ("runs", "list"),
        ("runs", "show", verify.UNKNOWN_RUN_ID),
        ("events", "--run", verify.UNKNOWN_RUN_ID),
        ("runs", "prune", "--keep", "0"),
    ]


def test_active_and_post_stop_queries_validate_run_and_watermark(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    active_run = _run_document(
        _RUN_ONE,
        session=verify.RUNTIME_SESSION,
        result=None,
        high_water_mark=3,
    )
    active_events = _event_documents(_RUN_ONE)[:4]
    _script_results(
        monkeypatch,
        (
            verify.CommandResult(0, verify.EXPECTED_RUNTIME_STATUS, b""),
            _canonical({"run_count": 1, "runs": [active_run]}),
            _canonical(active_run),
            _event_page(_RUN_ONE, active_events),
        ),
    )
    assert (
        verify._verify_active_runtime(  # pyright: ignore[reportPrivateUsage]
            tmp_path / "hiyelx",
            session=verify.RUNTIME_SESSION,
            workspace=tmp_path,
            environment={},
        )
        == _RUN_ONE
    )

    completed = _run_document(
        _RUN_ONE,
        session=verify.RUNTIME_SESSION,
        result="completed",
        high_water_mark=11,
    )
    all_events = _event_documents(_RUN_ONE)
    _script_results(
        monkeypatch,
        (_canonical(completed), _event_page(_RUN_ONE, all_events)),
    )
    assert (
        verify._verify_completed_run(  # pyright: ignore[reportPrivateUsage]
            tmp_path / "hiyelx",
            _RUN_ONE,
            workspace=tmp_path,
            environment={},
        )
        == all_events
    )


def test_interrupted_run_requires_sigint_result_events_and_canonical_end(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    interrupted = _run_document(
        _RUN_ONE,
        session=verify.INTERRUPT_RUNTIME_SESSION,
        result="interrupted",
        high_water_mark=11,
    )
    interrupted["stop_reason"] = "sigint"
    events = _event_documents(_RUN_ONE)
    _script_results(
        monkeypatch,
        (_canonical(interrupted), _event_page(_RUN_ONE, events)),
    )

    assert (
        verify._verify_interrupted_run(  # pyright: ignore[reportPrivateUsage]
            tmp_path / "hiyelx",
            _RUN_ONE,
            workspace=tmp_path,
            environment={},
        )
        == events
    )


def test_installed_interrupt_waits_for_active_evidence_before_sigint(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    trace: list[str] = []
    state_root = tmp_path / "state"
    session_directory = state_root / verify.INTERRUPT_RUNTIME_SESSION
    session_directory.mkdir(parents=True)
    fake_owner = FakeLifecycleOwner(
        trace,
        pid=101,
        cleanup_path=session_directory,
    )
    owner = cast(subprocess.Popen[bytes], fake_owner)
    owners: list[tuple[subprocess.Popen[bytes], str]] = []

    def start_owner(
        _executable: Path,
        _config_path: Path,
        *,
        session: str,
        workspace: Path,
        environment: Mapping[str, str],
        cleanup_registry: list[tuple[subprocess.Popen[bytes], str]] | None = None,
    ) -> subprocess.Popen[bytes]:
        assert workspace == tmp_path
        assert environment == {}
        assert cleanup_registry is owners
        if cleanup_registry is None:
            raise AssertionError
        trace.append("ready")
        cleanup_registry.append((owner, session))
        return owner

    def active_runtime(
        _executable: Path,
        *,
        session: str,
        excluded_run_ids: Sequence[str] = (),
        workspace: Path,
        environment: Mapping[str, str],
    ) -> str:
        assert session == verify.INTERRUPT_RUNTIME_SESSION
        assert excluded_run_ids == ()
        assert workspace == tmp_path
        assert environment == {}
        assert fake_owner.returncode is None
        trace.append("active-prefix")
        return _RUN_ONE

    def interrupted_run(
        _executable: Path,
        run_id: str,
        *,
        workspace: Path,
        environment: Mapping[str, str],
    ) -> list[dict[str, object]]:
        assert run_id == _RUN_ONE
        assert workspace == tmp_path
        assert environment == {}
        trace.append("interrupted-history")
        return _event_documents(run_id)

    monkeypatch.setattr(verify, "_start_installed_owner", start_owner)
    monkeypatch.setattr(verify, "_verify_active_runtime", active_runtime)
    monkeypatch.setattr(verify, "_verify_interrupted_run", interrupted_run)

    verify._verify_installed_interrupt_journey(  # pyright: ignore[reportPrivateUsage]
        tmp_path / "hiyelx",
        tmp_path / "sim-motor.yaml",
        session=verify.INTERRUPT_RUNTIME_SESSION,
        workspace=tmp_path,
        environment={},
        state_root=state_root,
        cleanup_registry=owners,
    )

    assert trace == ["ready", "active-prefix", "sigint", "interrupted-history"]
    assert fake_owner.returncode == 0
    assert not session_directory.exists()
    assert owners == []


def test_incomplete_crash_run_requires_exact_committed_prefix(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    incomplete = _run_document(
        _RUN_ONE,
        session=verify.CRASH_RUNTIME_SESSION,
        result=None,
        high_water_mark=3,
    )
    events = _event_documents(_RUN_ONE)[:4]
    _script_results(
        monkeypatch,
        (_canonical(incomplete), _event_page(_RUN_ONE, events)),
    )

    assert verify._verify_incomplete_run(  # pyright: ignore[reportPrivateUsage]
        tmp_path / "hiyelx",
        _RUN_ONE,
        session=verify.CRASH_RUNTIME_SESSION,
        workspace=tmp_path,
        environment={},
    ) == (incomplete, events)


def test_forced_crash_recovery_preserves_old_run_and_uses_new_id(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    trace: list[str] = []
    state_root = tmp_path / "state"
    session_directory = state_root / verify.CRASH_RUNTIME_SESSION
    session_directory.mkdir(parents=True)
    fake_crashed_owner = FakeLifecycleOwner(trace, pid=201)
    fake_recovery_owner = FakeLifecycleOwner(trace, pid=202)
    crashed_owner = cast(subprocess.Popen[bytes], fake_crashed_owner)
    recovery_owner = cast(subprocess.Popen[bytes], fake_recovery_owner)
    owners: list[tuple[subprocess.Popen[bytes], str]] = []
    starts = iter((crashed_owner, recovery_owner))
    active_runs = iter((_RUN_ONE, _RUN_TWO))
    incomplete = _run_document(
        _RUN_ONE,
        session=verify.CRASH_RUNTIME_SESSION,
        result=None,
        high_water_mark=3,
    )
    events = _event_documents(_RUN_ONE)[:4]
    incomplete_checks = 0

    def start_owner(
        _executable: Path,
        _config_path: Path,
        *,
        session: str,
        workspace: Path,
        environment: Mapping[str, str],
        cleanup_registry: list[tuple[subprocess.Popen[bytes], str]] | None = None,
    ) -> subprocess.Popen[bytes]:
        assert session == verify.CRASH_RUNTIME_SESSION
        assert workspace == tmp_path
        assert environment == {}
        assert cleanup_registry is owners
        if cleanup_registry is None:
            raise AssertionError
        selected = next(starts)
        if selected is recovery_owner:
            assert session_directory.exists()
            shutil.rmtree(session_directory)
            session_directory.mkdir()
        trace.append("ready")
        cleanup_registry.append((selected, session))
        return selected

    def active_runtime(
        _executable: Path,
        *,
        session: str,
        excluded_run_ids: Sequence[str] = (),
        workspace: Path,
        environment: Mapping[str, str],
    ) -> str:
        selected = next(active_runs)
        if selected == _RUN_ONE:
            assert excluded_run_ids == ()
            trace.append("crash-prefix")
        else:
            assert excluded_run_ids == (_RUN_ONE,)
            trace.append("recovery-prefix")
        assert session == verify.CRASH_RUNTIME_SESSION
        assert workspace == tmp_path
        assert environment == {}
        return selected

    def incomplete_run(
        _executable: Path,
        run_id: str,
        *,
        session: str,
        workspace: Path,
        environment: Mapping[str, str],
    ) -> tuple[dict[str, object], list[dict[str, object]]]:
        nonlocal incomplete_checks
        incomplete_checks += 1
        assert run_id == _RUN_ONE
        assert session == verify.CRASH_RUNTIME_SESSION
        assert workspace == tmp_path
        assert environment == {}
        trace.append("incomplete-check")
        return incomplete, events

    def stop_owner(
        owner: subprocess.Popen[bytes],
        _executable: Path,
        *,
        session: str,
        workspace: Path,
        environment: Mapping[str, str],
        state_root: Path,
    ) -> None:
        assert owner is recovery_owner
        assert session == verify.CRASH_RUNTIME_SESSION
        assert workspace == tmp_path
        assert environment == {}
        assert state_root == tmp_path / "state"
        trace.append("recovery-stop")
        fake_recovery_owner.returncode = 0
        shutil.rmtree(session_directory)

    def completed_run(
        _executable: Path,
        run_id: str,
        *,
        workspace: Path,
        environment: Mapping[str, str],
    ) -> list[dict[str, object]]:
        assert run_id == _RUN_TWO
        assert workspace == tmp_path
        assert environment == {}
        trace.append("recovery-completed")
        return _event_documents(run_id)

    monkeypatch.setattr(verify, "_start_installed_owner", start_owner)
    monkeypatch.setattr(verify, "_verify_active_runtime", active_runtime)
    monkeypatch.setattr(verify, "_verify_incomplete_run", incomplete_run)
    monkeypatch.setattr(verify, "_stop_installed_owner", stop_owner)
    monkeypatch.setattr(verify, "_verify_completed_run", completed_run)

    verify._verify_installed_crash_recovery_journey(  # pyright: ignore[reportPrivateUsage]
        tmp_path / "hiyelx",
        tmp_path / "sim-motor.yaml",
        session=verify.CRASH_RUNTIME_SESSION,
        workspace=tmp_path,
        environment={},
        state_root=state_root,
        cleanup_registry=owners,
    )

    assert fake_crashed_owner.returncode == -signal.SIGKILL
    assert incomplete_checks == 3
    assert trace == [
        "ready",
        "crash-prefix",
        "kill",
        "incomplete-check",
        "ready",
        "recovery-prefix",
        "incomplete-check",
        "recovery-stop",
        "recovery-completed",
        "incomplete-check",
    ]
    assert owners == []
    assert not session_directory.exists()


def test_two_run_persistence_and_event_text_json_cursor_contract(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first = _run_document(
        _RUN_ONE,
        session=verify.RUNTIME_SESSION,
        result="completed",
        high_water_mark=11,
    )
    second = _run_document(
        _RUN_TWO,
        session=verify.SECOND_RUNTIME_SESSION,
        result="completed",
        high_water_mark=11,
    )
    events = _event_documents(_RUN_TWO)
    _script_results(
        monkeypatch,
        (_canonical({"run_count": 2, "runs": [second, first]}),),
    )
    verify._verify_two_run_persistence(  # pyright: ignore[reportPrivateUsage]
        tmp_path / "hiyelx",
        first_run=_RUN_ONE,
        second_run=_RUN_TWO,
        workspace=tmp_path,
        environment={},
    )

    _script_results(
        monkeypatch,
        (
            verify.CommandResult(
                0,
                verify._render_event_page(  # pyright: ignore[reportPrivateUsage]
                    _RUN_TWO, events
                ),
                b"",
            ),
            _event_page(_RUN_TWO, events[4:]),
            _event_page(_RUN_TWO, events[:1]),
            _event_page(_RUN_TWO, events),
        ),
    )
    verify._verify_event_queries(  # pyright: ignore[reportPrivateUsage]
        tmp_path / "hiyelx",
        _RUN_TWO,
        events,
        workspace=tmp_path,
        environment={},
    )


def test_prune_keep_one_and_unknown_removed_run_contract(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    retained = _run_document(
        _RUN_TWO,
        session=verify.SECOND_RUNTIME_SESSION,
        result="completed",
        high_water_mark=11,
    )
    events = _event_documents(_RUN_TWO)
    _script_results(
        monkeypatch,
        (
            verify.CommandResult(0, b"deleted-runs=1\n", b""),
            verify.CommandResult(11, b"", b"error: runtime run is not found\n"),
            verify.CommandResult(11, b"", b"error: runtime run is not found\n"),
            _canonical(retained),
            _event_page(_RUN_TWO, events),
        ),
    )

    verify._verify_prune(  # pyright: ignore[reportPrivateUsage]
        tmp_path / "hiyelx",
        removed_run=_RUN_ONE,
        retained_run=_RUN_TWO,
        retained_events=events,
        workspace=tmp_path,
        environment={},
    )


def test_b1_active_safe_prune_preserves_two_incomplete_runs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    retained = _run_document(
        _RUN_TWO,
        session=verify.SECOND_RUNTIME_SESSION,
        result="completed",
        high_water_mark=11,
    )
    third = _run_document(
        _RUN_THREE,
        session=verify.THIRD_RUNTIME_SESSION,
        result=None,
        high_water_mark=3,
        started_at="2026-10-19T10:00:02.000000Z",
    )
    fourth = _run_document(
        _RUN_FOUR,
        session=verify.FOURTH_RUNTIME_SESSION,
        result=None,
        high_water_mark=3,
        started_at="2026-10-19T10:00:03.000000Z",
    )
    finalized_events = _event_documents(_RUN_TWO)
    third_events = _event_documents(_RUN_THREE)[:4]
    fourth_events = _event_documents(_RUN_FOUR)[:4]
    listing = _canonical({"run_count": 3, "runs": [fourth, third, retained]})
    third_status = verify.EXPECTED_RUNTIME_STATUS.replace(
        b"session=clean-install\n",
        f"session={verify.THIRD_RUNTIME_SESSION}\n".encode(),
        1,
    )
    fourth_status = verify.EXPECTED_RUNTIME_STATUS.replace(
        b"session=clean-install\n",
        f"session={verify.FOURTH_RUNTIME_SESSION}\n".encode(),
        1,
    )
    _script_results(
        monkeypatch,
        (
            verify.CommandResult(0, b"deleted-runs=1\n", b""),
            verify.CommandResult(11, b"", b"error: runtime run is not found\n"),
            verify.CommandResult(11, b"", b"error: runtime run is not found\n"),
            _canonical(retained),
            _event_page(_RUN_TWO, finalized_events),
            listing,
            verify.CommandResult(0, third_status, b""),
            listing,
            _canonical(third),
            _event_page(_RUN_THREE, third_events),
            verify.CommandResult(0, fourth_status, b""),
            listing,
            _canonical(fourth),
            _event_page(_RUN_FOUR, fourth_events),
        ),
    )

    verify._verify_b1_active_safe_prune(  # pyright: ignore[reportPrivateUsage]
        tmp_path / "hiyelx",
        removed_run=_RUN_ONE,
        retained_finalized_run=_RUN_TWO,
        retained_finalized_events=finalized_events,
        active_runs=(
            (verify.THIRD_RUNTIME_SESSION, _RUN_THREE),
            (verify.FOURTH_RUNTIME_SESSION, _RUN_FOUR),
        ),
        workspace=tmp_path,
        environment={},
    )


def test_b1_final_history_requires_deterministic_order_and_once_finalization(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    second = _run_document(
        _RUN_TWO,
        session=verify.SECOND_RUNTIME_SESSION,
        result="completed",
        high_water_mark=11,
    )
    third = _run_document(
        _RUN_THREE,
        session=verify.THIRD_RUNTIME_SESSION,
        result="completed",
        high_water_mark=11,
        started_at="2026-10-19T10:00:02.000000Z",
    )
    fourth = _run_document(
        _RUN_FOUR,
        session=verify.FOURTH_RUNTIME_SESSION,
        result="completed",
        high_water_mark=11,
        started_at="2026-10-19T10:00:03.000000Z",
    )
    _script_results(
        monkeypatch,
        (_canonical({"run_count": 3, "runs": [fourth, third, second]}),),
    )
    verify._verify_b1_final_history(  # pyright: ignore[reportPrivateUsage]
        tmp_path / "hiyelx",
        removed_run=_RUN_ONE,
        retained_runs=(_RUN_TWO, _RUN_THREE, _RUN_FOUR),
        workspace=tmp_path,
        environment={},
    )

    with pytest.raises(verify.VerificationFailure):
        verify._assert_distinct_canonical_run_ids(  # pyright: ignore[reportPrivateUsage]
            (_RUN_ONE, _RUN_ONE)
        )


def test_b1_final_history_rejects_noncanonical_order(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    second = _run_document(
        _RUN_TWO,
        session=verify.SECOND_RUNTIME_SESSION,
        result="completed",
        high_water_mark=11,
    )
    third = _run_document(
        _RUN_THREE,
        session=verify.THIRD_RUNTIME_SESSION,
        result="completed",
        high_water_mark=11,
        started_at="2026-10-19T10:00:02.000000Z",
    )
    fourth = _run_document(
        _RUN_FOUR,
        session=verify.FOURTH_RUNTIME_SESSION,
        result="completed",
        high_water_mark=11,
        started_at="2026-10-19T10:00:03.000000Z",
    )
    _script_results(
        monkeypatch,
        (_canonical({"run_count": 3, "runs": [second, third, fourth]}),),
    )
    with pytest.raises(verify.VerificationFailure):
        verify._verify_b1_final_history(  # pyright: ignore[reportPrivateUsage]
            tmp_path / "hiyelx",
            removed_run=_RUN_ONE,
            retained_runs=(_RUN_TWO, _RUN_THREE, _RUN_FOUR),
            workspace=tmp_path,
            environment={},
        )


def test_query_prune_and_json_failures_are_rejected_without_raw_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with pytest.raises(verify.VerificationFailure):
        verify._load_canonical_json_result(  # pyright: ignore[reportPrivateUsage]
            verify.CommandResult(0, b'{"private":"/secret/path"}\nextra', b"")
        )
    with pytest.raises(verify.VerificationFailure):
        verify._load_canonical_json_result(  # pyright: ignore[reportPrivateUsage]
            verify.CommandResult(10, b"", b"raw sqlite /secret/path")
        )

    _script_results(
        monkeypatch,
        (verify.CommandResult(10, b"", b"error: runtime history failed\n"),),
    )
    with pytest.raises(verify.VerificationFailure):
        verify._verify_prune(  # pyright: ignore[reportPrivateUsage]
            tmp_path / "hiyelx",
            removed_run=_RUN_ONE,
            retained_run=_RUN_TWO,
            retained_events=[],
            workspace=tmp_path,
            environment={},
        )


def test_non_contiguous_events_and_incorrect_high_water_mark_are_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events = _event_documents(_RUN_ONE)
    events[1]["sequence"] = 2
    with pytest.raises(verify.VerificationFailure):
        verify._load_event_page(  # pyright: ignore[reportPrivateUsage]
            _event_page(_RUN_ONE, events), run_id=_RUN_ONE
        )

    completed = _run_document(
        _RUN_ONE,
        session=verify.RUNTIME_SESSION,
        result="completed",
        high_water_mark=10,
    )
    _script_results(monkeypatch, (_canonical(completed),))
    with pytest.raises(verify.VerificationFailure):
        verify._verify_completed_run(  # pyright: ignore[reportPrivateUsage]
            tmp_path / "hiyelx",
            _RUN_ONE,
            workspace=tmp_path,
            environment={},
        )


@pytest.mark.parametrize(
    "arguments",
    (
        ("runtime", "status", "--session", verify.RUNTIME_SESSION),
        ("runtime", "stop", "--session", verify.RUNTIME_SESSION),
        ("runtime", "events", "--run", _RUN_ONE),
        ("runtime", "runs", "prune", "--keep", "1"),
    ),
)
def test_installed_runtime_command_timeouts_are_verification_failures(
    arguments: tuple[str, ...],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def timeout(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess[bytes]:
        raise subprocess.TimeoutExpired(cmd=arguments, timeout=1)

    monkeypatch.setattr(subprocess, "run", timeout)
    with pytest.raises(verify.VerificationFailure):
        verify._run_command(  # pyright: ignore[reportPrivateUsage]
            (str(tmp_path / "hiyelx"), *arguments), tmp_path, {}
        )


def test_fault_command_timeout_is_real_bounded_and_reaps_child(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(verify, "_FAULT_TIMEOUT_SECONDS", 0.25)
    pid_path = tmp_path / "fault-child.pid"
    child = (
        "import os, sys, time; "
        "from pathlib import Path; "
        "Path(sys.argv[1]).write_text(str(os.getpid()), encoding='utf-8'); "
        "time.sleep(30)"
    )
    started = time.monotonic()

    with pytest.raises(verify.VerificationFailure):
        verify._require_bounded_exact_result(  # pyright: ignore[reportPrivateUsage]
            (sys.executable, "-c", child, str(pid_path)),
            workspace=tmp_path,
            environment=dict(os.environ),
            returncode=0,
            stdout=b"",
            stderr=b"",
        )

    assert time.monotonic() - started < 2.0
    pid = int(pid_path.read_text(encoding="utf-8"))
    with pytest.raises(ProcessLookupError):
        os.kill(pid, 0)


def test_installed_cli_launch_failure_is_a_verification_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def missing(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess[bytes]:
        raise FileNotFoundError("/private/task/missing-installed-cli")

    monkeypatch.setattr(subprocess, "run", missing)
    with pytest.raises(verify.VerificationFailure):
        verify._run_command(  # pyright: ignore[reportPrivateUsage]
            (str(tmp_path / "missing-hiyelx"), "runtime", "runs", "list"),
            tmp_path,
            {},
        )


@pytest.mark.parametrize(
    "stderr",
    (
        b"connection refused",
        b"command timed out",
        b"permission denied by runtime store",
        b"failed to bind runtime control socket",
    ),
)
def test_ambiguous_product_errors_are_not_environment_blocked(stderr: bytes) -> None:
    with pytest.raises(verify.VerificationFailure):
        verify._require_success(  # pyright: ignore[reportPrivateUsage]
            verify.CommandResult(1, b"", stderr), environment_sensitive=True
        )


def test_explicit_package_dns_failure_is_environment_blocked() -> None:
    with pytest.raises(verify.VerificationEnvironmentBlocked):
        verify._require_success(  # pyright: ignore[reportPrivateUsage]
            verify.CommandResult(
                1,
                b"",
                b"Could not resolve host: package-index.invalid",
            ),
            environment_sensitive=True,
        )


def test_product_failure_never_uses_environment_blocked_exit(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail() -> str:
        raise verify.VerificationFailure("connection refused /private/task/path")

    monkeypatch.setattr(verify, "run_clean_install_verification", fail)
    assert verify.main() == verify.FAILURE
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "error: clean-install verification failed\n"


def test_unsupported_platform_is_environment_blocked(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sys, "platform", "unsupported")
    with pytest.raises(verify.VerificationEnvironmentBlocked):
        verify.verify_installed_runtime_workflow(
            tmp_path / "hiyelx",
            tmp_path / "sim-motor.yaml",
            python=tmp_path / "python",
            workspace=tmp_path,
            environment={},
        )


def test_platform_short_control_path_boundary() -> None:
    verify._assert_short_control_path(  # pyright: ignore[reportPrivateUsage]
        Path(os.sep) / "hx",
        verify.RUNTIME_SESSION,
    )
    too_long = Path("/") / ("x" * verify._MAX_UNIX_SOCKET_PATH_BYTES)  # pyright: ignore[reportPrivateUsage]
    with pytest.raises(verify.VerificationEnvironmentBlocked):
        verify._assert_short_control_path(  # pyright: ignore[reportPrivateUsage]
            too_long,
            verify.RUNTIME_SESSION,
        )


def test_b1_state_prefix_prevents_macos_socket_budget_regression() -> None:
    deterministic_suffix = "12345678"
    boundary_parent = Path(os.sep) / ("x" * 58)
    current_state_root = boundary_parent / (
        f"{verify._RUNTIME_STATE_DIRECTORY_PREFIX}{deterministic_suffix}"  # pyright: ignore[reportPrivateUsage]
    )
    current_socket = current_state_root / verify.FOURTH_RUNTIME_SESSION / "control.sock"
    legacy_state_root = boundary_parent / f"hxctl-{deterministic_suffix}"
    legacy_socket = legacy_state_root / verify.FOURTH_RUNTIME_SESSION / "control.sock"

    assert verify._RUNTIME_STATE_DIRECTORY_PREFIX == "hx-"  # pyright: ignore[reportPrivateUsage]
    assert len(os.fsencode(current_socket)) == verify._MAX_UNIX_SOCKET_PATH_BYTES  # pyright: ignore[reportPrivateUsage]
    verify._assert_short_control_path(  # pyright: ignore[reportPrivateUsage]
        current_state_root,
        verify.FOURTH_RUNTIME_SESSION,
    )
    assert len(os.fsencode(legacy_socket)) > verify._MAX_UNIX_SOCKET_PATH_BYTES  # pyright: ignore[reportPrivateUsage]


@pytest.mark.parametrize("line_count", (1, 2))
def test_readiness_protocol_uses_one_total_deadline(
    line_count: int,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(verify, "_READINESS_TIMEOUT_SECONDS", 0.2)
    payload = repr(b"\n".join(verify.EXPECTED_RUNTIME_READY[:line_count]) + b"\n")
    owner = subprocess.Popen(
        [
            sys.executable,
            "-c",
            f"import sys,time; sys.stdout.buffer.write({payload}); "
            "sys.stdout.buffer.flush(); time.sleep(30)",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    started = time.monotonic()
    try:
        with pytest.raises(verify.VerificationFailure):
            verify._read_owner_lines(  # pyright: ignore[reportPrivateUsage]
                owner, len(verify.EXPECTED_RUNTIME_READY)
            )
        assert time.monotonic() - started < 2.0
    finally:
        owner.terminate()
        owner.wait(timeout=5)
    assert owner.poll() is not None


def test_readiness_protocol_accepts_normal_three_line_sequence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(verify, "_READINESS_TIMEOUT_SECONDS", 1.0)
    payload = repr(b"\n".join(verify.EXPECTED_RUNTIME_READY) + b"\n")
    owner = subprocess.Popen(
        [sys.executable, "-c", f"import sys; sys.stdout.buffer.write({payload})"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        assert (
            verify._read_owner_lines(  # pyright: ignore[reportPrivateUsage]
                owner, 3
            )
            == verify.EXPECTED_RUNTIME_READY
        )
    finally:
        owner.wait(timeout=5)
    assert owner.poll() is not None


def test_owner_early_exit_is_rejected_and_reaped(tmp_path: Path) -> None:
    executable = tmp_path / "early-owner"
    executable.write_text(
        "#!/usr/bin/env python3\n"
        "import sys\n"
        "print('DNS error from installed runtime', file=sys.stderr)\n"
        "raise SystemExit(7)\n",
        encoding="utf-8",
    )
    executable.chmod(0o700)
    config = tmp_path / "sim-motor.yaml"
    config.write_text('schema_version: "1"\nresources: []\n', encoding="utf-8")

    with pytest.raises(verify.VerificationFailure):
        verify._start_installed_owner(  # pyright: ignore[reportPrivateUsage]
            executable,
            config,
            session=verify.RUNTIME_SESSION,
            workspace=tmp_path,
            environment=dict(os.environ),
        )


def test_stop_failure_does_not_hide_owner_cleanup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(verify, "_CLEANUP_TIMEOUT_SECONDS", 0.1)
    owner = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    def fail_stop(
        _command: Sequence[str],
        _cwd: Path,
        _environment: Mapping[str, str],
    ) -> verify.CommandResult:
        return verify.CommandResult(8, b"", b"error: runtime cleanup failed\n")

    monkeypatch.setattr(verify, "_run_command", fail_stop)
    try:
        with pytest.raises(verify.VerificationFailure):
            verify._stop_installed_owner(  # pyright: ignore[reportPrivateUsage]
                owner,
                tmp_path / "hiyelx",
                session=verify.RUNTIME_SESSION,
                workspace=tmp_path,
                environment=dict(os.environ),
                state_root=tmp_path / "state",
            )
    finally:
        verify._cleanup_owner(  # pyright: ignore[reportPrivateUsage]
            owner,
            tmp_path / "hiyelx",
            session=verify.RUNTIME_SESSION,
            workspace=tmp_path,
            environment=dict(os.environ),
        )
    assert owner.poll() is not None


def test_owner_exit_timeout_is_failure_and_reaps_owner(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(verify, "_OWNER_EXIT_TIMEOUT_SECONDS", 0.1)
    monkeypatch.setattr(verify, "_CLEANUP_TIMEOUT_SECONDS", 0.1)
    owner = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    def successful_stop(
        _command: Sequence[str],
        _cwd: Path,
        _environment: Mapping[str, str],
    ) -> verify.CommandResult:
        return verify.CommandResult(
            0,
            f"session={verify.RUNTIME_SESSION}\nruntime=stopped\n".encode(),
            b"",
        )

    monkeypatch.setattr(verify, "_run_command", successful_stop)
    with pytest.raises(verify.VerificationFailure):
        verify._stop_installed_owner(  # pyright: ignore[reportPrivateUsage]
            owner,
            tmp_path / "missing-hiyelx",
            session=verify.RUNTIME_SESSION,
            workspace=tmp_path,
            environment=dict(os.environ),
            state_root=tmp_path / "state",
        )
    assert owner.poll() is not None


def test_cleanup_stop_timeout_uses_bounded_kill_fallback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(verify, "_CLEANUP_TIMEOUT_SECONDS", 0.1)
    owner = subprocess.Popen(
        [
            sys.executable,
            "-c",
            "import signal,time; signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(30)",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    time.sleep(0.05)

    def timeout(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess[bytes]:
        raise subprocess.TimeoutExpired(cmd=("hiyelx", "runtime", "stop"), timeout=0.1)

    monkeypatch.setattr(subprocess, "run", timeout)
    started = time.monotonic()
    verify._cleanup_owner(  # pyright: ignore[reportPrivateUsage]
        owner,
        tmp_path / "hiyelx",
        session=verify.RUNTIME_SESSION,
        workspace=tmp_path,
        environment=dict(os.environ),
    )
    assert time.monotonic() - started < 1.0
    assert owner.poll() is not None


def test_b1_cleanup_attempts_both_owners_when_one_cleanup_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(verify, "_CLEANUP_TIMEOUT_SECONDS", 0.1)
    third_owner = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    fourth_owner = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    owners = [
        (third_owner, verify.THIRD_RUNTIME_SESSION),
        (fourth_owner, verify.FOURTH_RUNTIME_SESSION),
    ]
    real_cleanup = verify._cleanup_owner  # pyright: ignore[reportPrivateUsage]
    attempted: list[str] = []

    def cleanup_then_fail(
        owner: subprocess.Popen[bytes],
        executable: Path,
        *,
        session: str,
        workspace: Path,
        environment: Mapping[str, str],
    ) -> None:
        attempted.append(session)
        real_cleanup(
            owner,
            executable,
            session=session,
            workspace=workspace,
            environment=environment,
        )
        if session == verify.FOURTH_RUNTIME_SESSION:
            raise verify.VerificationFailure

    monkeypatch.setattr(verify, "_cleanup_owner", cleanup_then_fail)
    cleanup_error = verify._cleanup_registered_owners(  # pyright: ignore[reportPrivateUsage]
        owners,
        tmp_path / "hiyelx",
        workspace=tmp_path,
        environment=dict(os.environ),
    )

    assert isinstance(cleanup_error, verify.VerificationFailure)
    assert attempted == [verify.FOURTH_RUNTIME_SESSION, verify.THIRD_RUNTIME_SESSION]
    assert third_owner.poll() is not None
    assert fourth_owner.poll() is not None
    assert owners == []


@pytest.mark.parametrize("abort_type", (KeyboardInterrupt, SystemExit))
def test_cleanup_preserves_base_exception_after_reaping_owner(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    abort_type: type[BaseException],
) -> None:
    monkeypatch.setattr(verify, "_CLEANUP_TIMEOUT_SECONDS", 0.1)
    owner = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    def abort(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess[bytes]:
        raise abort_type

    monkeypatch.setattr(subprocess, "run", abort)
    with pytest.raises(abort_type):
        verify._cleanup_owner(  # pyright: ignore[reportPrivateUsage]
            owner,
            tmp_path / "hiyelx",
            session=verify.RUNTIME_SESSION,
            workspace=tmp_path,
            environment=dict(os.environ),
        )
    assert owner.poll() is not None


def test_readiness_timeout_terminates_owner_and_removes_artifacts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(verify, "_READINESS_TIMEOUT_SECONDS", 0.2)
    monkeypatch.setattr(verify, "_CLEANUP_TIMEOUT_SECONDS", 0.2)
    executable = tmp_path / "partial-owner"
    executable.write_text(
        """#!/usr/bin/env python3
import os
import shutil
import signal
import time
from pathlib import Path

state = Path(os.environ["HIYELX_RUNTIME_STATE_DIR"]) / "clean-install"
marker = Path(os.environ["HIYELX_TEST_OWNER_MARKER"])
state.mkdir(parents=True)
marker.write_text(str(os.getpid()), encoding="utf-8")

def cleanup(_signum, _frame):
    shutil.rmtree(state, ignore_errors=True)
    marker.unlink(missing_ok=True)
    raise SystemExit(0)

signal.signal(signal.SIGTERM, cleanup)
print("session=clean-install", flush=True)
while True:
    time.sleep(1)
""",
        encoding="utf-8",
    )
    executable.chmod(0o700)
    config = tmp_path / "sim-motor.yaml"
    config.write_text('schema_version: "1"\nresources: []\n', encoding="utf-8")
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    marker = tmp_path / "owner.pid"
    environment = dict(os.environ)
    environment["HIYELX_TEST_OWNER_MARKER"] = str(marker)

    with pytest.raises(verify.VerificationFailure):
        verify._start_installed_owner(  # pyright: ignore[reportPrivateUsage]
            executable,
            config,
            session=verify.RUNTIME_SESSION,
            workspace=workspace,
            environment=environment,
        )

    assert not marker.exists()


def test_manual_runbook_cleanup_is_fail_closed() -> None:
    runbook = (REPOSITORY_ROOT / "docs/development/clean-install-and-demo.md").read_text(
        encoding="utf-8"
    )

    assert "cleanup_hiyelx_rto3_manual()" in runbook
    assert 'case "$cleanup_target" in' in runbook
    assert '"$TEMP_BASE"/hiyelx-rto3-manual.*)' in runbook
    assert 'test "$cleanup_parent" != "$TEMP_BASE"' in runbook
    assert 'test -L "$cleanup_target"' in runbook
    assert 'rm -rf -- "$cleanup_target"' in runbook
    assert "error: refusing unsafe RTO-3 cleanup" in runbook
    assert '\nrm -rf "$WORK_DIR"\n' not in runbook


def test_installed_negative_cli_matrix_is_byte_exact_and_mutation_free(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    executable = tmp_path / "hiyelx"
    config = tmp_path / "sim-motor.yaml"
    config.write_text('schema_version: "1"\nresources: []\n', encoding="utf-8")
    state = tmp_path / "state"
    history = tmp_path / "history"
    environment = {
        "HIYELX_RUNTIME_STATE_DIR": str(state),
        "HIYELX_RUNTIME_HISTORY_DIR": str(history),
    }
    observed: list[tuple[str, ...]] = []
    observed_timeouts: list[float] = []

    def run(
        command: Sequence[str],
        _cwd: Path,
        _environment: Mapping[str, str],
        *,
        timeout_seconds: float = 180.0,
    ) -> verify.CommandResult:
        observed_timeouts.append(timeout_seconds)
        arguments = tuple(command[1:])
        observed.append(arguments)
        if arguments[:2] == ("runtime", "start"):
            if arguments[-1] == "../private":
                return verify.CommandResult(3, b"", verify._INVALID_SESSION)  # pyright: ignore[reportPrivateUsage]
            return verify.CommandResult(2, b"", verify._INVALID_CONFIGURATION)  # pyright: ignore[reportPrivateUsage]
        if arguments[:2] in {
            ("runtime", "status"),
            ("runtime", "stop"),
        }:
            stderr = (
                verify._INVALID_SESSION  # pyright: ignore[reportPrivateUsage]
                if arguments[-1] == "../private"
                else verify._SESSION_NOT_RUNNING  # pyright: ignore[reportPrivateUsage]
            )
            return verify.CommandResult(3 if arguments[-1] == "../private" else 5, b"", stderr)
        if (
            arguments[:3] == ("runtime", "runs", "show")
            or arguments[:2]
            == (
                "runtime",
                "events",
            )
            and "--after" not in arguments
            and "--limit" not in arguments
        ):
            return verify.CommandResult(11, b"", verify._RUN_NOT_FOUND)  # pyright: ignore[reportPrivateUsage]
        if arguments[:3] == ("runtime", "runs", "list"):
            return verify.CommandResult(2, b"", verify._list_limit_error())  # pyright: ignore[reportPrivateUsage]
        if arguments[:2] == ("runtime", "events"):
            stderr = (
                verify._event_after_error()  # pyright: ignore[reportPrivateUsage]
                if "--after" in arguments
                else verify._event_limit_error()  # pyright: ignore[reportPrivateUsage]
            )
            return verify.CommandResult(2, b"", stderr)
        if arguments[:3] == ("runtime", "runs", "prune"):
            stderr = (
                verify._prune_missing_error()  # pyright: ignore[reportPrivateUsage]
                if "--keep" not in arguments
                else verify._prune_value_error()  # pyright: ignore[reportPrivateUsage]
            )
            return verify.CommandResult(2, b"", stderr)
        raise AssertionError(arguments)

    monkeypatch.setattr(verify, "_run_command", run)
    verify._verify_invalid_cli_inputs(  # pyright: ignore[reportPrivateUsage]
        executable,
        config,
        workspace=tmp_path,
        environment=environment,
        state_root=state,
        history_root=history,
    )

    assert len(observed) == 22
    assert observed_timeouts == [verify._FAULT_TIMEOUT_SECONDS] * 22  # pyright: ignore[reportPrivateUsage]
    assert not state.exists()
    assert not history.exists()


def test_private_wire_matrix_uses_one_connection_per_exact_probe(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: list[tuple[bytes, bool]] = []

    def request(
        _socket_path: Path,
        message: bytes,
        *,
        shutdown_write: bool,
    ) -> bytes:
        observed.append((message, shutdown_write))
        if b'"command":"unknown"' in message:
            return verify._UNKNOWN_COMMAND_REPLY  # pyright: ignore[reportPrivateUsage]
        return verify._INVALID_REQUEST_REPLY  # pyright: ignore[reportPrivateUsage]

    monkeypatch.setattr(verify, "_raw_control_request", request)
    verify._verify_private_control_probes(  # pyright: ignore[reportPrivateUsage]
        tmp_path / "control.sock",
        session=verify.NEGATIVE_RUNTIME_SESSION,
    )

    assert len(observed) == 10
    assert sum(shutdown for _message, shutdown in observed) == 1
    assert any(len(message) > 8192 for message, _shutdown in observed)
    assert any(b'"protocol_version":true' in message for message, _ in observed)
    assert any(b'"protocol_version":1.0' in message for message, _ in observed)
    assert any(message.count(b'"command"') == 2 for message, _ in observed)


@pytest.mark.parametrize(
    "unsafe",
    (
        b"Traceback (most recent call last)",
        b"/private/task/history.sqlite3",
        b"credential=top-secret",
        b"sqlite backend exception",
        b"device=/dev/tty.usbserial",
        b"pid=12345",
        b"address=0xfeedbeef",
        b'schema_version: "1"',
        b'{"command":broken',
    ),
)
def test_central_product_output_sanitizer_rejects_every_forbidden_class(
    unsafe: bytes,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(verify, "_product_evidence", [unsafe])  # pyright: ignore[reportPrivateUsage]
    with pytest.raises(verify.VerificationFailure):
        verify._verify_sanitized_product_outputs(  # pyright: ignore[reportPrivateUsage]
            forbidden_paths=(Path("/private/task"),)
        )


def test_central_product_output_sanitizer_accepts_canonical_surfaces(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        verify,
        "_product_evidence",
        [
            b"session=clean-negative\nruntime=running\ncontrol=ready\n",
            verify._INVALID_REQUEST_REPLY,  # pyright: ignore[reportPrivateUsage]
            verify._HISTORY_FAILED,  # pyright: ignore[reportPrivateUsage]
            verify._CLEANUP_FAILED,  # pyright: ignore[reportPrivateUsage]
        ],
    )
    verify._verify_sanitized_product_outputs(  # pyright: ignore[reportPrivateUsage]
        forbidden_paths=(Path("/private/task"),)
    )


def test_history_event_faults_use_the_event_query_surface() -> None:
    assert verify._history_fault_arguments(  # pyright: ignore[reportPrivateUsage]
        "event-corrupt", event_run_id="run-id"
    ) == ("runtime", "events", "--run", "run-id")
    assert verify._history_fault_arguments(  # pyright: ignore[reportPrivateUsage]
        "event-gap", event_run_id="run-id"
    ) == ("runtime", "events", "--run", "run-id")
    assert verify._history_fault_arguments(  # pyright: ignore[reportPrivateUsage]
        "watermark-corrupt", event_run_id="run-id"
    ) == ("runtime", "events", "--run", "run-id")
    assert verify._history_fault_arguments(  # pyright: ignore[reportPrivateUsage]
        "run-corrupt", event_run_id="run-id"
    ) == ("runtime", "runs", "list")


def test_unsafe_history_file_mode_fixtures_preserve_source_bytes_and_modes(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source-history"
    source.mkdir(mode=0o700)
    database = source / "history.sqlite3"
    lock = source / "history.lock"
    database.write_bytes(b"database-bytes")
    lock.write_bytes(b"lock-bytes")
    os.chmod(database, 0o600)
    os.chmod(lock, 0o600)
    fixtures = tmp_path / "fixtures"
    fixtures.mkdir(mode=0o700)
    source_before = verify._tree_snapshot(source)  # pyright: ignore[reportPrivateUsage]

    unsafe_database, unsafe_lock = verify._create_unsafe_history_mode_fixtures(  # pyright: ignore[reportPrivateUsage]
        source,
        history_fixtures=fixtures,
    )

    assert verify._tree_snapshot(source) == source_before  # pyright: ignore[reportPrivateUsage]
    assert stat.S_IMODE(unsafe_database.stat().st_mode) == 0o700
    assert stat.S_IMODE((unsafe_database / "history.sqlite3").stat().st_mode) == 0o644
    assert stat.S_IMODE((unsafe_database / "history.lock").stat().st_mode) == 0o600
    assert (unsafe_database / "history.sqlite3").read_bytes() == b"database-bytes"
    assert stat.S_IMODE(unsafe_lock.stat().st_mode) == 0o700
    assert stat.S_IMODE((unsafe_lock / "history.sqlite3").stat().st_mode) == 0o600
    assert stat.S_IMODE((unsafe_lock / "history.lock").stat().st_mode) == 0o644
    assert (unsafe_lock / "history.lock").read_bytes() == b"lock-bytes"


def test_cleanup_fault_harness_uses_real_orchestration_and_records_order(
    tmp_path: Path,
) -> None:
    executable = Path(sys.executable).parent / "hiyelx"
    assert executable.is_file()
    workspace = tmp_path / "workspace"
    workspace.mkdir(mode=0o700)
    home = workspace / "home"
    temporary = workspace / "temp"
    home.mkdir(mode=0o700)
    temporary.mkdir(mode=0o700)
    environment = dict(os.environ)
    environment["HOME"] = str(home)
    environment["TMPDIR"] = str(temporary)
    owners: list[tuple[subprocess.Popen[bytes], str]] = []
    config = REPOSITORY_ROOT / "examples/configs/sim-motor.yaml"

    with tempfile.TemporaryDirectory(
        prefix=verify._RUNTIME_STATE_DIRECTORY_PREFIX,  # pyright: ignore[reportPrivateUsage]
        dir=verify._short_temporary_parent(),  # pyright: ignore[reportPrivateUsage]
    ) as state_name:
        state_root = Path(state_name)
        environment["HIYELX_RUNTIME_STATE_DIR"] = state_name
        trace = verify._verify_installed_cleanup_failure(  # pyright: ignore[reportPrivateUsage]
            Path(sys.executable),
            executable,
            config,
            workspace=workspace,
            environment=environment,
            state_root=state_root,
            cleanup_registry=owners,
        )

        assert trace.cleanup_calls == ("safe_stop", "shutdown")
        assert trace.session_cleanup_calls == (False, True)
        assert trace.persist_calls == 2
        assert owners == []
        assert not (state_root / verify.CLEANUP_RUNTIME_SESSION).exists()
        assert tuple(state_root.iterdir()) == ()
        assert not (workspace / "cleanup-failure-trace.json").exists()
