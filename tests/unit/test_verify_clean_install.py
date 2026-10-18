import os
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

    def __call__(
        self,
        command: Sequence[str],
        cwd: Path,
        environment: Mapping[str, str],
    ) -> verify.CommandResult:
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


def test_readiness_timeout_terminates_owner_and_removes_artifacts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(verify, "_READINESS_TIMEOUT_SECONDS", 0.2)
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
        verify.verify_installed_runtime_workflow(
            executable,
            config,
            workspace=workspace,
            environment=environment,
        )

    assert not marker.exists()
