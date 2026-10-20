import json
import os
import shutil
import subprocess
import sys
import time
from collections.abc import Mapping, Sequence
from pathlib import Path
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
            installed = (
                environment_path
                / "lib/python3.12/site-packages/hiyelx/__init__.py"
            )
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
            assert environment["HIYELX_RUNTIME_STATE_DIR"] == str(
                cwd / "runtime-state"
            )
            runtime_index = command.index("runtime")
            runtime_command = command[runtime_index + 1]
            if runtime_command == "start":
                return verify.CommandResult(
                    0,
                    b"\n".join(verify.EXPECTED_RUNTIME_READY)
                    + b"\nruntime=stopped\n",
                    b"",
                )
            if runtime_command == "status":
                return verify.CommandResult(0, verify.EXPECTED_RUNTIME_STATUS, b"")
            if runtime_command == "stop":
                return verify.CommandResult(0, verify.EXPECTED_RUNTIME_STOP, b"")
        return verify.CommandResult(0, b"", b"")


_RUN_ONE = "10000000-0000-4000-8000-000000000001"
_RUN_TWO = "20000000-0000-4000-8000-000000000002"


def _canonical(document: object) -> verify.CommandResult:
    return verify.CommandResult(
        0,
        (
            json.dumps(document, ensure_ascii=True, separators=(",", ":"), sort_keys=True)
            + "\n"
        ).encode("ascii"),
        b"",
    )


def _run_document(
    run_id: str,
    *,
    session: str,
    result: str | None,
    high_water_mark: int,
) -> dict[str, object]:
    return {
        "ended_at": None if result is None else "2026-10-19T10:00:01.000000Z",
        "event_high_water_mark": high_water_mark,
        "result": result,
        "run_id": run_id,
        "session_id": session,
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
        "blocked: clean-install verification requires package access "
        "and loopback support\n"
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
    assert captured.out.splitlines() == [
        "wheel=hiyelx-0.2.0a1-py3-none-any.whl",
        *verify.HISTORY_SUCCESS_MARKERS,
        "clean-install=passed",
    ]


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
    assert verify._verify_completed_run(  # pyright: ignore[reportPrivateUsage]
        tmp_path / "hiyelx",
        _RUN_ONE,
        workspace=tmp_path,
        environment={},
    ) == all_events


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
            "import signal,time; signal.signal(signal.SIGTERM, signal.SIG_IGN); "
            "time.sleep(30)",
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
    runbook = (
        REPOSITORY_ROOT / "docs/development/clean-install-and-demo.md"
    ).read_text(encoding="utf-8")

    assert "cleanup_hiyelx_rto3_manual()" in runbook
    assert 'case "$cleanup_target" in' in runbook
    assert '"$TEMP_BASE"/hiyelx-rto3-manual.*)' in runbook
    assert 'test "$cleanup_parent" != "$TEMP_BASE"' in runbook
    assert 'test -L "$cleanup_target"' in runbook
    assert 'rm -rf -- "$cleanup_target"' in runbook
    assert "error: refusing unsafe RTO-3 cleanup" in runbook
    assert '\nrm -rf "$WORK_DIR"\n' not in runbook
