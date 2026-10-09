"""Safe, deterministic scaffold generation for external motor drivers."""

from __future__ import annotations

import keyword
import re
import shutil
import tempfile
from pathlib import Path
from string import Template

from hiyelx.sdk.errors import (
    InvalidScaffoldModelNameError,
    InvalidScaffoldPackageNameError,
    ScaffoldParentMissingError,
    ScaffoldTargetExistsError,
)

_PACKAGE_NAME = re.compile(r"[a-z][a-z0-9_]*\Z")

_INIT_TEMPLATE = Template(
    '''"""Generated HIYELX motor-driver scaffold."""

from .$package_name import (
    MODEL_NAME,
    $class_name,
    ${class_name}Settings,
    $register_function,
)

__all__ = [
    "MODEL_NAME",
    "$class_name",
    "${class_name}Settings",
    "$register_function",
]
'''
)

_DRIVER_TEMPLATE = Template(
    '''"""Hardware-free starting point for a HIYELX motor driver.

Replace the in-memory operations with a bounded vendor transport only after the
contract tests pass. Do not place vendor SDK types in application-facing APIs.
"""

from math import isfinite
from typing import Self

from hiyelx.components import Motor, MotorCommand, MotorState
from hiyelx.models import ModelRegistry
from hiyelx.resources import ResourceIdentity
from hiyelx.sdk import register_motor_driver
from pydantic import BaseModel, ConfigDict, model_validator

MODEL_NAME = $model_literal


class ${class_name}Settings(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    initial_position_radians: float = 0.0
    max_abs_velocity_rad_s: float = 1.0

    @model_validator(mode="after")
    def _values_must_be_finite_and_limit_positive(self) -> Self:
        if not isfinite(self.initial_position_radians):
            raise ValueError("initial_position_radians must be finite")
        if not isfinite(self.max_abs_velocity_rad_s) or self.max_abs_velocity_rad_s <= 0.0:
            raise ValueError("max_abs_velocity_rad_s must be positive and finite")
        return self


class $class_name(Motor):
    """Deterministic in-memory scaffold; this is not a physical backend."""

    def __init__(self, identity: ResourceIdentity, settings: ${class_name}Settings) -> None:
        super().__init__(identity)
        self._settings = settings
        self._motor_state = MotorState(settings.initial_position_radians, 0.0)
        self._events: list[str] = []

    @property
    def events(self) -> tuple[str, ...]:
        return tuple(self._events)

    async def _on_start(self) -> None:
        self._events.append("startup")
        self._motor_state = MotorState(
            self._motor_state.angular_position_radians,
            0.0,
        )

    async def _on_shutdown(self) -> None:
        self._events.append("shutdown")
        self._motor_state = MotorState(
            self._motor_state.angular_position_radians,
            0.0,
        )

    async def _apply_command(self, command: MotorCommand) -> None:
        velocity = command.angular_velocity_radians_per_second
        if abs(velocity) > self._settings.max_abs_velocity_rad_s:
            raise ValueError("motor command exceeds configured scaffold limit")
        self._events.append(f"command:{velocity}")
        self._motor_state = MotorState(
            self._motor_state.angular_position_radians,
            velocity,
        )

    async def _read_state(self) -> MotorState:
        return self._motor_state


def $register_function(registry: ModelRegistry) -> None:
    register_motor_driver(
        registry,
        model_name=MODEL_NAME,
        settings_type=${class_name}Settings,
        builder=$class_name,
    )
'''
)

_TEST_TEMPLATE = Template(
    '''from typing import cast

import pytest
from hiyelx.components import Motor, MotorCommand
from hiyelx.config import ResourceDefinition
from hiyelx.models import ModelCreationError, ModelRegistry
from hiyelx.resources import LifecycleState, Resource, ResourceIdentity
from hiyelx.sdk import (
    MotorComplianceFixture,
    register_motor_driver,
    run_motor_compliance,
)

from $package_name import (
    MODEL_NAME,
    $class_name,
    ${class_name}Settings,
    $register_function,
)


def _definition(settings: dict[str, object]) -> ResourceDefinition:
    return ResourceDefinition(
        identity=ResourceIdentity("example_motor"),
        model=MODEL_NAME,
        settings=settings,
    )


def test_registration_builds_created_motor_without_io() -> None:
    registry = ModelRegistry()
    $register_function(registry)

    resource = registry.create(
        _definition(
            {
                "initial_position_radians": 1.25,
                "max_abs_velocity_rad_s": 0.5,
            }
        )
    )

    assert isinstance(resource, $class_name)
    assert resource.state is LifecycleState.CREATED


@pytest.mark.parametrize(
    "settings",
    [
        {"initial_position_radians": "1.25"},
        {"initial_position_radians": 0.0, "unknown": True},
        {"max_abs_velocity_rad_s": 0.0},
    ],
)
def test_invalid_settings_are_rejected(settings: dict[str, object]) -> None:
    registry = ModelRegistry()
    $register_function(registry)

    with pytest.raises(ModelCreationError):
        registry.create(_definition(settings))


def _reject_invalid_settings() -> None:
    registry = ModelRegistry()
    $register_function(registry)
    registry.create(_definition({"initial_position_radians": "1.25"}))


def _reject_non_motor_builder() -> None:
    registry = ModelRegistry()

    def invalid_builder(
        identity: ResourceIdentity,
        settings: ${class_name}Settings,
    ) -> Motor:
        del settings
        return cast(Motor, Resource(identity))

    register_motor_driver(
        registry,
        model_name="motor.generated.invalid",
        settings_type=${class_name}Settings,
        builder=invalid_builder,
    )
    registry.create(
        ResourceDefinition(
            identity=ResourceIdentity("invalid_motor"),
            model="motor.generated.invalid",
            settings={"initial_position_radians": 0.0},
        )
    )


@pytest.mark.asyncio
async def test_software_only_motor_compliance() -> None:
    built: list[$class_name] = []

    def build() -> $class_name:
        motor = $class_name(
            ResourceIdentity("example_motor"),
            ${class_name}Settings(
                initial_position_radians=1.25,
                max_abs_velocity_rad_s=0.5,
            ),
        )
        built.append(motor)
        return motor

    report = await run_motor_compliance(
        MotorComplianceFixture(
            software_only=True,
            expected_identity=ResourceIdentity("example_motor"),
            motor_factory=build,
            command=MotorCommand(0.25),
            verify_command_effect=lambda state: (
                state.angular_position_radians == 1.25
                and state.angular_velocity_radians_per_second == 0.25
            ),
            verify_stopped=lambda state: (
                state.angular_velocity_radians_per_second == 0.0
            ),
            reject_invalid_settings=_reject_invalid_settings,
            reject_non_motor_builder=_reject_non_motor_builder,
            event_snapshot=lambda: built[0].events if built else (),
            expected_cleanup_order=("command:0.0", "shutdown"),
        )
    )

    assert report.final_lifecycle is LifecycleState.STOPPED
    assert report.events[-2:] == ("command:0.0", "shutdown")
'''
)

_CONFIG_TEMPLATE = Template(
    '''schema_version: "1"
resources:
  - identity: example_motor
    model: $model_name
    settings:
      initial_position_radians: 0.0
      max_abs_velocity_rad_s: 0.5
'''
)

_README_TEMPLATE = Template(
    '''# $class_name HIYELX driver scaffold

This generated package is a hardware-free, in-memory starting point for model
`$model_name`. It demonstrates strict settings, explicit registration, and the
HIYELX software-only Motor compliance harness.

Run the generated contract tests from this directory in an environment that
already contains HIYELX and its development test dependencies:

```bash
pytest
```

Before replacing the in-memory operations with a vendor SDK:

1. Keep vendor types and errors behind the Motor contract.
2. Add a deterministic fake transport and failure injection.
3. Offload blocking calls from the asyncio event loop.
4. Serialize access to a shared transport.
5. Add bounded command conversion and operation deadlines.
6. Preserve primary failures and ordered best-effort cleanup evidence.
7. Keep physical tests explicitly opted in and separate from software tests.

This scaffold does not authorize hardware access, torque, or motion and is not
evidence of physical acceptance, hard-real-time behavior, or certified safety.
Never pass a production physical backend to the compliance harness: lifecycle
startup in a real driver may enable torque.
'''
)

_PYPROJECT = '''[tool.pytest.ini_options]
asyncio_mode = "auto"
pythonpath = ["."]
testpaths = ["tests"]
'''


def create_motor_driver_scaffold(
    output: Path,
    *,
    package_name: str,
    model_name: str,
) -> tuple[Path, ...]:
    """Atomically create a non-overwriting, hardware-free driver scaffold."""
    _validate_package_name(package_name)
    _validate_model_name(model_name)
    if output.exists() or output.is_symlink():
        raise ScaffoldTargetExistsError
    parent = output.parent
    if not parent.is_dir():
        raise ScaffoldParentMissingError

    class_name = "".join(part.capitalize() for part in package_name.split("_"))
    register_function = f"register_{package_name}"
    substitutions = {
        "package_name": package_name,
        "class_name": class_name,
        "register_function": register_function,
        "model_name": model_name,
        "model_literal": repr(model_name),
    }
    files = {
        Path("README.md"): _README_TEMPLATE.substitute(substitutions),
        Path("pyproject.toml"): _PYPROJECT,
        Path("runtime.yaml"): _CONFIG_TEMPLATE.substitute(substitutions),
        Path(package_name, "__init__.py"): _INIT_TEMPLATE.substitute(substitutions),
        Path(package_name, f"{package_name}.py"): _DRIVER_TEMPLATE.substitute(
            substitutions
        ),
        Path("tests", "test_driver.py"): _TEST_TEMPLATE.substitute(substitutions),
    }

    staging = Path(tempfile.mkdtemp(prefix=".hiyelx-scaffold-", dir=parent))
    try:
        for relative_path, content in files.items():
            destination = staging / relative_path
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(content, encoding="utf-8")
        staging.replace(output)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return tuple(sorted(files))


def _validate_package_name(package_name: str) -> None:
    if _PACKAGE_NAME.fullmatch(package_name) is None or keyword.iskeyword(package_name):
        raise InvalidScaffoldPackageNameError(package_name)


def _validate_model_name(model_name: str) -> None:
    if not model_name.strip() or "\n" in model_name or "\r" in model_name:
        raise InvalidScaffoldModelNameError(model_name)
