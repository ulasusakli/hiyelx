# HIYELX Software Evidence Index

## Purpose

This index separates the historical `v0.1.0` Software Developer Preview release
evidence from later Module/Driver SDK Alpha evidence on `main`, external human
usability evidence, and deferred physical evidence. It does not replace test
results or grant physical acceptance.

The GitHub pre-release
[`v0.1.0`](https://github.com/ulasusakli/hiyelx/releases/tag/v0.1.0) targets
`e3801ed43ec4b173dae765ac583055314defce50`. The historical `0.1.0-rc.1`
label belongs to the candidate evidence pack; the released package version is
`0.1.0`. No PyPI or other package-registry publication occurred.

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
| LIC-1 | Implemented | Founder-authorized [`Apache License 2.0`](../../LICENSE) and PEP 639 package metadata | `Apache-2.0` license expression and canonical license included in wheel metadata | Clean-install verifier rejects metadata drift, missing license files, or changed license content |

The table above describes the implementation evidence available for the
`v0.1.0` release decision. “Implemented” does not mean physically accepted,
hard real-time, or certified safe.

## Post-release Module/Driver SDK Alpha evidence on `main`

The following work was integrated after the `v0.1.0` tag and is not part of
that release snapshot. It must currently be evaluated from repository source;
it has not been published to PyPI or another package registry and carries no
compatibility guarantee.

| Capability | Integration SHA | Evidence |
|---|---|---|
| HCA-SDK-1/HCA-SDK-2 | `29551e1262e85fa0ca0c6c4a5278d64d47eef8d0` | Public [`register_motor_driver`](../../src/hiyelx/sdk/motor_driver.py) helper, strict driver-owned settings validation, CLI [`scaffold`](../../src/hiyelx/sdk/scaffold.py), [SDK guide](../development/module-driver-sdk.md), [`test_motor_driver.py`](../../tests/unit/sdk/test_motor_driver.py), [`test_scaffold.py`](../../tests/unit/sdk/test_scaffold.py), and external-driver integration tests under [`tests/integration/sdk/`](../../tests/integration/sdk/) |
| HCA-SDK-3 | `003e765862aa2c847b0c2224e2d9748a3cdc0b8f` | Software-only [`compliance.py`](../../src/hiyelx/sdk/compliance.py), [porting checklist](../development/motor-driver-porting-checklist.md), [`test_compliance.py`](../../tests/unit/sdk/test_compliance.py), and generated scaffold compliance coverage |
| HCA-SDK-4 | `d1cfb3d083836c207864c1c84e01787a9db78294` | Independently buildable external-driver scaffold, [`verify_external_driver_install.py`](../../scripts/verify_external_driver_install.py), [`test_verify_external_driver_install.py`](../../tests/unit/test_verify_external_driver_install.py), clean non-editable installation, source-tree import rejection, and configuration to explicit registry to Runtime Manager to loopback gRPC to Motor proof |

The verified HCA-SDK-4 baseline was 286 passed, 0 failed, 1 skipped physical
test, 0 deselected, and 0 environment-blocked. Both the existing clean-install
verifier and external-driver verifier passed. GitHub Actions Quality gate
[`38126922129`](https://github.com/ulasusakli/hiyelx/actions/runs/38126922129)
succeeded for `d1cfb3d083836c207864c1c84e01787a9db78294`.

Current package metadata on `main` still identifies the project as `0.1.0`.
`HCA-VERSION-1` must separately decide the next package, tag, and release
identity; this index does not resolve that decision.

## External developer evidence

EDR-1 is recorded separately in
[`2026-10-08-external-developer-dry-run.md`](2026-10-08-external-developer-dry-run.md).
The founder accepted that bounded session at commit `32e47a0`. The record shows
a fresh-clone, exact deterministic SIM transcript, and clean non-editable wheel
installation, together with explicit evidence limitations. It closes only the
External Developer Dry Run gate and is not evidence of physical behavior or
broad ecosystem usability.

No external human developer dry run has yet accepted the post-release
Module/Driver SDK Alpha workflow. That separate gate is HCA-SDK-5.

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
- License: founder-authorized Apache License 2.0 implemented and verified in the wheel
- Historical candidate label: `0.1.0-rc.1` evidence-pack revision
- Software Developer Preview: published as GitHub pre-release `v0.1.0`
- Release target: `e3801ed43ec4b173dae765ac583055314defce50`
- Package version: `0.1.0`
- Package registry: no PyPI or other registry publication
- Post-release SDK Alpha: present only on later `main` commits listed above
- Physical acceptance: deferred; no physical validation claim
