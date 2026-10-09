# Module/Driver SDK Alpha

HIYELX applications can integrate a trusted external motor driver without
editing HIYELX core. The application explicitly imports the driver package and
registers its stable model name in its own `ModelRegistry` instance.

Configuration remains data. HIYELX does not import configuration-sourced
Python paths, scan packages, or discover entry points.

## Generate a safe starting point

The CLI creates a hardware-free external-driver package, example config, and
baseline contract tests in a new directory:

```bash
hiyelx scaffold motor-driver ./acme-driver \
  --package-name acme_motor_driver \
  --model-name motor.acme.reference
```

The target path must not exist. The command refuses to overwrite any existing
file or directory and renders the scaffold through a temporary sibling before
an atomic rename. It creates:

```text
acme-driver/
  README.md
  pyproject.toml
  runtime.yaml
  acme_motor_driver/
    __init__.py
    acme_motor_driver.py
  tests/
    test_driver.py
```

The generated motor is deliberately in-memory. Its five baseline tests use the
reusable software-only compliance harness to cover construction without I/O,
strict settings rejection, lifecycle, command/state, stop, shutdown, and
ordered cleanup evidence. Run them from the generated directory in a
development environment that contains HIYELX, pytest, and pytest-asyncio:

```bash
pytest
```

Passing the generated tests is software-contract evidence only. It is not
evidence that a vendor transport, physical device, torque behavior, movement,
or cleanup path has been accepted.

## Run software-only compliance

`MotorComplianceFixture` and `run_motor_compliance` provide a small reusable
contract runner without a pytest runtime dependency. The fixture supplies the
motor factory, bounded command, driver-owned state predicates, settings and
builder rejection probes, and an immutable ordered-event snapshot. The runner
returns an immutable `MotorComplianceReport` or raises a typed sanitized
`MotorComplianceFailure` chained from the underlying failure.

The explicit `software_only=True` declaration is mandatory and is checked
before the motor factory or any lifecycle callback runs. Never pass a physical
production backend to this harness: calling `start()` on a real driver may open
a device or enable torque. Compliance execution is authorized only with an
in-memory motor or deterministic fake transport. Passing results are
software-contract evidence, not physical acceptance.

Command effects and stopped behavior are supplied as fixture callbacks. The
harness does not assume that physical feedback immediately equals a commanded
velocity. Driver fakes may inject startup, command, or shutdown failures; the
typed compliance error preserves the failure as its cause and retains the
ordered event snapshot without including arbitrary backend text in its public
message.

## Define strict settings

External drivers define a frozen Pydantic settings model. Unknown fields and
implicit type coercion should be rejected:

```python
from pydantic import BaseModel, ConfigDict


class ExampleMotorSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    device: str
    max_abs_velocity_rad_s: float
```

## Implement the Motor contract

The driver subclasses the vendor-neutral `Motor` contract. Application-facing
position and velocity use radians and radians per second. Vendor SDK types,
registers, exceptions, and device assumptions remain inside the driver:

```python
from hiyelx.components import Motor, MotorCommand, MotorState
from hiyelx.resources import ResourceIdentity


class ExampleMotor(Motor):
    def __init__(
        self,
        identity: ResourceIdentity,
        settings: ExampleMotorSettings,
    ) -> None:
        super().__init__(identity)
        self._settings = settings

    async def _on_start(self) -> None:
        ...

    async def _on_shutdown(self) -> None:
        ...

    async def _apply_command(self, command: MotorCommand) -> None:
        ...

    async def _read_state(self) -> MotorState:
        ...
```

Blocking vendor SDK calls must not run on the asyncio event loop. Driver
authors remain responsible for transport serialization, operation deadlines,
safe unit conversion, bounded commands, typed errors, and best-effort cleanup.

## Register explicitly

The public `register_motor_driver` helper validates settings in strict mode and
requires the builder to return a `Motor`:

```python
from hiyelx.models import ModelRegistry
from hiyelx.sdk import register_motor_driver

EXAMPLE_MOTOR_MODEL = "motor.example.external"


def register_example_motor(registry: ModelRegistry) -> None:
    register_motor_driver(
        registry,
        model_name=EXAMPLE_MOTOR_MODEL,
        settings_type=ExampleMotorSettings,
        builder=ExampleMotor,
    )
```

The application owns composition:

```python
registry = ModelRegistry()
register_example_motor(registry)
```

The corresponding local configuration uses only the stable model name and
validated settings:

```yaml
schema_version: "1"
resources:
  - identity: external_motor
    model: motor.example.external
    settings:
      device: /dev/example
      max_abs_velocity_rad_s: 0.5
```

Loading or validating this document performs no import, discovery, serial
access, or lifecycle action. The Runtime Manager creates and owns the resource
only after the trusted application has registered the factory.

## Alpha contract

The current SDK alpha guarantees:

- explicit instance-local registration;
- strict model-specific settings validation;
- one stable model name per registered builder;
- runtime rejection when a builder does not return a `Motor`;
- compatibility with configuration, Runtime Manager, and Motor gRPC paths;
- no requirement to edit HIYELX core for an external driver;
- a non-overwriting CLI scaffold with runnable baseline contract tests.

The alpha does not yet provide package discovery, entry points, a project
publisher, a complete reusable vendor-driver certification suite, compatibility
promises, shared-bus ownership, retry/reconnect policy, or physical acceptance
for an external driver.

Use the
[`Motor Driver Porting Checklist`](motor-driver-porting-checklist.md) before
adapting the scaffold to alternative hardware.
