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
            write_test_wheel(output / "hiyelx-0.1.0-py3-none-any.whl")
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
        elif command[-2:] == ("demo", "sim-motor"):
            if self.fail_demo:
                return verify.CommandResult(1, b"", b"secret backend failure")
            return verify.CommandResult(0, self.expected, b"")
        return verify.CommandResult(0, b"", b"")


def write_test_wheel(
    path: Path,
    *,
    license_expression: str = verify.EXPECTED_LICENSE_EXPRESSION,
    include_license: bool = True,
) -> None:
    with ZipFile(path, "w") as wheel:
        wheel.writestr(
            "hiyelx-0.1.0.dist-info/METADATA",
            "Metadata-Version: 2.4\n"
            "Name: hiyelx\n"
            "Version: 0.1.0\n"
            f"License-Expression: {license_expression}\n"
            "License-File: LICENSE\n\n",
        )
        if include_license:
            wheel.write(
                REPOSITORY_ROOT / "LICENSE",
                "hiyelx-0.1.0.dist-info/licenses/LICENSE",
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


def test_wheel_license_metadata_drift_is_rejected(tmp_path: Path) -> None:
    wheel = tmp_path / "hiyelx-0.1.0-py3-none-any.whl"
    write_test_wheel(wheel, license_expression="MIT")

    with pytest.raises(verify.VerificationFailure):
        verify.assert_wheel_license(wheel, repository_root=REPOSITORY_ROOT)


def test_missing_wheel_license_file_is_rejected(tmp_path: Path) -> None:
    wheel = tmp_path / "hiyelx-0.1.0-py3-none-any.whl"
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

    assert wheel == "hiyelx-0.1.0-py3-none-any.whl"
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
