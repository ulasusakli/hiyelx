from pathlib import Path

import pytest

from hiyelx.sdk import (
    InvalidScaffoldModelNameError,
    InvalidScaffoldPackageNameError,
    ScaffoldParentMissingError,
    ScaffoldTargetExistsError,
    create_motor_driver_scaffold,
)


def test_scaffold_creates_complete_deterministic_starting_point(tmp_path: Path) -> None:
    output = tmp_path / "generated"

    created = create_motor_driver_scaffold(
        output,
        package_name="acme_motor_driver",
        model_name="motor.acme.reference",
    )

    assert created == (
        Path("README.md"),
        Path("acme_motor_driver/__init__.py"),
        Path("acme_motor_driver/acme_motor_driver.py"),
        Path("pyproject.toml"),
        Path("runtime.yaml"),
        Path("tests/test_driver.py"),
    )
    assert tuple(
        sorted(path.relative_to(output) for path in output.rglob("*") if path.is_file())
    ) == created
    assert "motor.acme.reference" in (output / "runtime.yaml").read_text(
        encoding="utf-8"
    )
    driver = output / "acme_motor_driver/acme_motor_driver.py"
    assert "class AcmeMotorDriver(Motor):" in driver.read_text(encoding="utf-8")
    generated_tests = (output / "tests/test_driver.py").read_text(encoding="utf-8")
    assert "run_motor_compliance" in generated_tests
    assert "software_only=True" in generated_tests
    for relative_path in created:
        if relative_path.suffix == ".py":
            source = (output / relative_path).read_text(encoding="utf-8")
            compile(source, str(relative_path), "exec")


def test_scaffold_never_overwrites_existing_target(tmp_path: Path) -> None:
    output = tmp_path / "existing"
    output.mkdir()
    sentinel = output / "keep.txt"
    sentinel.write_text("user-data", encoding="utf-8")

    with pytest.raises(ScaffoldTargetExistsError):
        create_motor_driver_scaffold(
            output,
            package_name="acme_motor_driver",
            model_name="motor.acme.reference",
        )

    assert sentinel.read_text(encoding="utf-8") == "user-data"
    assert tuple(output.iterdir()) == (sentinel,)


def test_scaffold_never_overwrites_existing_file(tmp_path: Path) -> None:
    output = tmp_path / "existing"
    output.write_text("user-data", encoding="utf-8")

    with pytest.raises(ScaffoldTargetExistsError):
        create_motor_driver_scaffold(
            output,
            package_name="acme_motor_driver",
            model_name="motor.acme.reference",
        )

    assert output.read_text(encoding="utf-8") == "user-data"


def test_scaffold_never_overwrites_dangling_symlink(tmp_path: Path) -> None:
    output = tmp_path / "existing"
    output.symlink_to(tmp_path / "missing")

    with pytest.raises(ScaffoldTargetExistsError):
        create_motor_driver_scaffold(
            output,
            package_name="acme_motor_driver",
            model_name="motor.acme.reference",
        )

    assert output.is_symlink()
    assert output.readlink() == tmp_path / "missing"


@pytest.mark.parametrize("package_name", ["", "Acme", "acme-driver", "class"])
def test_scaffold_rejects_invalid_package_name(
    tmp_path: Path,
    package_name: str,
) -> None:
    with pytest.raises(InvalidScaffoldPackageNameError):
        create_motor_driver_scaffold(
            tmp_path / "generated",
            package_name=package_name,
            model_name="motor.acme.reference",
        )


@pytest.mark.parametrize("model_name", ["", "  ", "motor.acme\nreference"])
def test_scaffold_rejects_invalid_model_name(tmp_path: Path, model_name: str) -> None:
    with pytest.raises(InvalidScaffoldModelNameError):
        create_motor_driver_scaffold(
            tmp_path / "generated",
            package_name="acme_motor_driver",
            model_name=model_name,
        )


def test_scaffold_requires_existing_parent(tmp_path: Path) -> None:
    with pytest.raises(ScaffoldParentMissingError):
        create_motor_driver_scaffold(
            tmp_path / "missing" / "generated",
            package_name="acme_motor_driver",
            model_name="motor.acme.reference",
        )
