from collections.abc import Mapping, Sequence
from pathlib import Path

import pytest

from hiyelx.sdk import create_motor_driver_scaffold
from scripts import verify_external_driver_install as verify

REPOSITORY_ROOT = Path(__file__).parents[2]


class FakeRunner:
    def __init__(
        self,
        *,
        hiyelx_source_import: bool = False,
        driver_source_import: bool = False,
        fail_external_build: bool = False,
        fail_install: bytes | None = None,
        transcript: tuple[str, ...] = verify.EXPECTED_TRANSCRIPT,
    ) -> None:
        self.hiyelx_source_import = hiyelx_source_import
        self.driver_source_import = driver_source_import
        self.fail_external_build = fail_external_build
        self.fail_install = fail_install
        self.transcript = transcript

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
            source = Path(command[-1])
            if source.name == "driver-source" and self.fail_external_build:
                return verify.CommandResult(1, b"", b"build failed")
            output.mkdir(parents=True)
            wheel_name = (
                "acme_motor_driver-0.1.0-py3-none-any.whl"
                if source.name == "driver-source"
                else "hiyelx-0.1.0-py3-none-any.whl"
            )
            (output / wheel_name).write_bytes(b"wheel")
        elif "venv" in command:
            binaries = Path(command[-1]) / "bin"
            binaries.mkdir(parents=True)
            (binaries / "python").write_text("", encoding="utf-8")
            (binaries / "hiyelx").write_text("", encoding="utf-8")
        elif "pip" in command and "install" in command:
            if self.fail_install is not None:
                return verify.CommandResult(1, b"", self.fail_install)
        elif command[-1] == "--version":
            return verify.CommandResult(0, b"Python 3.12.14\n", b"")
        elif "scaffold" in command:
            output = Path(command[3])
            create_motor_driver_scaffold(
                output,
                package_name=verify.PACKAGE_NAME,
                model_name=verify.MODEL_NAME,
            )
            return verify.CommandResult(
                0,
                b"scaffold=motor-driver\n"
                b"package=acme_motor_driver\n"
                b"model=motor.acme.reference\n"
                b"files=6\n",
                b"",
            )
        elif "-c" in command:
            workspace = cwd.parent
            environment_path = workspace / "venv"
            hiyelx_path = (
                REPOSITORY_ROOT / "src/hiyelx/__init__.py"
                if self.hiyelx_source_import
                else environment_path
                / "lib/python3.12/site-packages/hiyelx/__init__.py"
            )
            driver_source = workspace / "driver-source"
            driver_path = (
                driver_source / "acme_motor_driver/__init__.py"
                if self.driver_source_import
                else environment_path
                / "lib/python3.12/site-packages/acme_motor_driver/__init__.py"
            )
            return verify.CommandResult(
                0,
                f"{hiyelx_path}\n{driver_path}\n".encode(),
                b"",
            )
        elif command[-1].endswith("verify_external_driver.py") or (
            len(command) > 1 and command[1].endswith("verify_external_driver.py")
        ):
            return verify.CommandResult(
                0,
                ("\n".join(self.transcript) + "\n").encode(),
                b"",
            )
        return verify.CommandResult(0, b"", b"")


def test_successful_external_driver_verification_and_cleanup(tmp_path: Path) -> None:
    report = verify.run_external_driver_verification(
        repository_root=REPOSITORY_ROOT,
        runner=FakeRunner(),
        temporary_parent=tmp_path,
    )

    assert report.hiyelx_wheel == "hiyelx-0.1.0-py3-none-any.whl"
    assert report.external_wheel == "acme_motor_driver-0.1.0-py3-none-any.whl"
    assert report.transcript == verify.EXPECTED_TRANSCRIPT
    assert tuple(tmp_path.iterdir()) == ()


@pytest.mark.parametrize(
    ("runner", "forbidden_name"),
    [
        (FakeRunner(hiyelx_source_import=True), "hiyelx"),
        (FakeRunner(driver_source_import=True), "external driver"),
    ],
)
def test_source_imports_are_rejected_and_cleaned(
    tmp_path: Path,
    runner: FakeRunner,
    forbidden_name: str,
) -> None:
    del forbidden_name
    with pytest.raises(verify.ExternalDriverVerificationFailure):
        verify.run_external_driver_verification(
            repository_root=REPOSITORY_ROOT,
            runner=runner,
            temporary_parent=tmp_path,
        )

    assert tuple(tmp_path.iterdir()) == ()


def test_missing_and_multiple_wheels_are_rejected(tmp_path: Path) -> None:
    with pytest.raises(verify.ExternalDriverVerificationFailure):
        verify.require_single_wheel(tmp_path, "*.whl")

    (tmp_path / "one.whl").write_bytes(b"")
    (tmp_path / "two.whl").write_bytes(b"")
    with pytest.raises(verify.ExternalDriverVerificationFailure):
        verify.require_single_wheel(tmp_path, "*.whl")


def test_scaffold_layout_drift_is_rejected(tmp_path: Path) -> None:
    scaffold = tmp_path / "scaffold"
    scaffold.mkdir()
    (scaffold / "README.md").write_text("incomplete", encoding="utf-8")

    with pytest.raises(verify.ExternalDriverVerificationFailure):
        verify.assert_scaffold_layout(scaffold)


def test_external_wheel_build_failure_is_cleaned(tmp_path: Path) -> None:
    with pytest.raises(verify.ExternalDriverVerificationFailure):
        verify.run_external_driver_verification(
            repository_root=REPOSITORY_ROOT,
            runner=FakeRunner(fail_external_build=True),
            temporary_parent=tmp_path,
        )

    assert tuple(tmp_path.iterdir()) == ()


@pytest.mark.parametrize(
    ("stderr", "expected"),
    [
        (b"dependency conflict", verify.ExternalDriverVerificationFailure),
        (b"DNS resolution failed", verify.ExternalDriverEnvironmentBlocked),
    ],
)
def test_installation_failure_is_classified_and_cleaned(
    tmp_path: Path,
    stderr: bytes,
    expected: type[Exception],
) -> None:
    with pytest.raises(expected):
        verify.run_external_driver_verification(
            repository_root=REPOSITORY_ROOT,
            runner=FakeRunner(fail_install=stderr),
            temporary_parent=tmp_path,
        )

    assert tuple(tmp_path.iterdir()) == ()


def test_transcript_drift_is_rejected_and_cleaned(tmp_path: Path) -> None:
    with pytest.raises(verify.ExternalDriverVerificationFailure):
        verify.run_external_driver_verification(
            repository_root=REPOSITORY_ROOT,
            runner=FakeRunner(transcript=("drifted",)),
            temporary_parent=tmp_path,
        )

    assert tuple(tmp_path.iterdir()) == ()


def test_failure_output_is_sanitized(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail() -> verify.ExternalDriverVerificationReport:
        raise RuntimeError("credential=top-secret /private/tmp/hidden")

    monkeypatch.setattr(verify, "run_external_driver_verification", fail)
    assert verify.main() == verify.FAILURE
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "error: external-driver verification failed\n"
    assert "top-secret" not in captured.err
    assert "/private/tmp" not in captured.err


def test_environment_blocked_output_is_sanitized(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def blocked() -> verify.ExternalDriverVerificationReport:
        raise verify.ExternalDriverEnvironmentBlocked("secret index URL")

    monkeypatch.setattr(verify, "run_external_driver_verification", blocked)
    assert verify.main() == verify.ENVIRONMENT_BLOCKED
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == (
        "blocked: external-driver verification requires package access "
        "and loopback support\n"
    )
    assert "secret" not in captured.err
