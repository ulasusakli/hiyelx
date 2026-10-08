# HIYELX Software Evidence Index

## Purpose

This index maps the Software Preview RC to inspectable repository evidence. It
does not replace test results, grant physical acceptance, or declare the
Software Developer Preview released.

## Software implementation evidence

| Capability | Status | Architecture or contract | Implementation evidence | Verification evidence |
|---|---|---|---|---|
| Foundation | Implemented | [`../../README.md`](../../README.md), [`../../pyproject.toml`](../../pyproject.toml) | Python 3.12 package, uv lock, installable CLI, and [minimal CI](../../.github/workflows/ci.yml) | [`tests/unit/test_import.py`](../../tests/unit/test_import.py), lock, Ruff, Pyright, and pytest gates |
| Resource Core | Implemented | Public exports in [`../../src/hiyelx/resources/__init__.py`](../../src/hiyelx/resources/__init__.py) | [`../../src/hiyelx/resources/_resource.py`](../../src/hiyelx/resources/_resource.py) | [`tests/unit/resources/test_resource.py`](../../tests/unit/resources/test_resource.py) and [`test_reliability.py`](../../tests/unit/resources/test_reliability.py) |
| Motor API and deterministic simulation | Implemented | Public Motor contract in [`../../src/hiyelx/components/motor.py`](../../src/hiyelx/components/motor.py) | [`../../src/hiyelx/simulation/motor.py`](../../src/hiyelx/simulation/motor.py) with explicit simulated time | [`tests/unit/components/test_motor.py`](../../tests/unit/components/test_motor.py) and [`tests/unit/simulation/test_simulated_motor.py`](../../tests/unit/simulation/test_simulated_motor.py) |
| Configuration and Model Registry | Implemented | [`../architecture/configuration-and-model-registry.md`](../architecture/configuration-and-model-registry.md) | [`../../src/hiyelx/config/`](../../src/hiyelx/config/) and [`../../src/hiyelx/models/`](../../src/hiyelx/models/) | [`tests/unit/config/test_loader.py`](../../tests/unit/config/test_loader.py) and [`tests/unit/models/test_registry.py`](../../tests/unit/models/test_registry.py) |
| Runtime Manager | Implemented | [`../architecture/runtime-manager.md`](../architecture/runtime-manager.md) | [`../../src/hiyelx/runtime/manager.py`](../../src/hiyelx/runtime/manager.py) and deterministic planning | [`tests/unit/runtime/`](../../tests/unit/runtime/) |
| gRPC Boundary | Implemented for loopback use | [`../architecture/grpc-boundary.md`](../architecture/grpc-boundary.md), [`../../proto/hiyelx/v1/motor.proto`](../../proto/hiyelx/v1/motor.proto) | [`../../src/hiyelx/rpc/`](../../src/hiyelx/rpc/) and committed generated modules | [`tests/unit/rpc/`](../../tests/unit/rpc/) and [`tests/integration/rpc/test_motor_grpc.py`](../../tests/integration/rpc/test_motor_grpc.py) |
| Real Reference Driver | Software implementation complete; physical acceptance deferred | [`../hardware/dynamixel-xl430-w250-t.md`](../hardware/dynamixel-xl430-w250-t.md) | [`../../src/hiyelx/drivers/dynamixel/`](../../src/hiyelx/drivers/dynamixel/) behind the HAL | Fake-transport/unit suites and [`tests/integration/drivers/test_dynamixel_grpc.py`](../../tests/integration/drivers/test_dynamixel_grpc.py); opt-in physical test is not run |
| RB-1 | Implemented | [`../architecture/reliability-rb1.md`](../architecture/reliability-rb1.md) | Typed operation deadlines, sanitized faults, health degradation, and late blocking-call serialization | Resource, Motor, Runtime, RPC, and DYNAMIXEL reliability tests |
| RB-2 | Implemented | [`../architecture/reliability-rb2.md`](../architecture/reliability-rb2.md) | Best-effort safe-stop, immutable health propagation, and instance-local structured events | [`tests/unit/runtime/test_safe_stop.py`](../../tests/unit/runtime/test_safe_stop.py) and associated regression suites |
| DX-1 | Implemented | [README quickstart](../../README.md) | Installable CLI and deterministic loopback SIM demo in [`../../src/hiyelx/cli.py`](../../src/hiyelx/cli.py) | [`tests/unit/test_cli.py`](../../tests/unit/test_cli.py) and canonical [`sim-motor.txt`](../../examples/expected/sim-motor.txt) |
| DR-1 | Implemented | [`../development/clean-install-and-demo.md`](../development/clean-install-and-demo.md) | [`../../scripts/verify_clean_install.py`](../../scripts/verify_clean_install.py) and CI wheel smoke gate | [`tests/unit/test_verify_clean_install.py`](../../tests/unit/test_verify_clean_install.py) plus isolated non-editable wheel verification |

All entries above are software evidence. “Implemented” does not mean released,
physically accepted, hard real-time, or certified safe.

## External developer evidence

EDR-1 is recorded separately in
[`2026-10-08-external-developer-dry-run.md`](2026-10-08-external-developer-dry-run.md).
The founder accepted that bounded session at commit `32e47a0`. The record shows
a fresh-clone, exact deterministic SIM transcript, and clean non-editable wheel
installation, together with explicit evidence limitations. It closes only the
External Developer Dry Run gate and is not evidence of physical behavior or
broad ecosystem usability.

The reusable participant materials remain:

- [`../development/external-developer-dry-run.md`](../development/external-developer-dry-run.md)
- [`external-developer-dry-run-template.md`](external-developer-dry-run-template.md)

## Deferred physical hardware evidence

The repository contains an XL430-W250-T driver and an explicitly opt-in physical
acceptance test. Ordinary quality gates do not select that test, and SPRC-1 does
not open a serial device, enable torque, command physical movement, or claim a
hardware result.

No accepted evidence currently closes:

- Real Reference Driver physical acceptance;
- Physical Hardware Proof; or
- the physical portion of the full PRE-SEED milestone.

The required bench boundary and deferred limitations are documented in
[`../hardware/dynamixel-xl430-w250-t.md`](../hardware/dynamixel-xl430-w250-t.md).

## Release-decision evidence

- Candidate pack:
  [`../releases/software-preview-0.1.0-rc.1.md`](../releases/software-preview-0.1.0-rc.1.md)
- Delivery state: [`../../PRESEED.md`](../../PRESEED.md)
- Implementation source of truth: GitHub `main`
- License: no explicit license exists; founder decision required before release
- Software Developer Preview: not released
- Git tag, GitHub Release, and package publication: not created
