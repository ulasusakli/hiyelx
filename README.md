# HIYELX

HIYELX is a hardware-independent robotics software platform for building, running, and operating intelligent machines through stable resource APIs, configuration-driven topology, pluggable hardware models, and a local-first robot runtime.

## Current stage

**PRE-SEED — Hardware-Connected Developer Alpha, software track**

The bounded [`v0.1.0` Software Developer Preview](https://github.com/ulasusakli/hiyelx/releases/tag/v0.1.0)
was published as a GitHub pre-release from commit
`e3801ed43ec4b173dae765ac583055314defce50`. The `0.1.0-rc.1` name identifies
the historical evidence-pack revision; the released package and wheel version
is `0.1.0`.

The current objective is to prove the core technical thesis:

> Change the hardware, not the application.

The same application-level API should run against deterministic simulation and at least one real hardware driver, with hardware selection resolved through configuration and the model registry.

## Local simulation quickstart

Install the locked development environment, validate the canonical demo
configuration, and run the hardware-free loopback workflow:

```bash
uv sync --all-groups
uv run hiyelx validate-config examples/configs/sim-motor.yaml
uv run hiyelx demo sim-motor
```

Expected validation output:

```text
configuration=valid
```

The canonical deterministic 14-line output is
[`examples/expected/sim-motor.txt`](examples/expected/sim-motor.txt). Verify the
built wheel in a fresh, non-editable Python 3.12 environment with:

```bash
uv run python scripts/verify_clean_install.py
```

See
[`docs/development/clean-install-and-demo.md`](docs/development/clean-install-and-demo.md)
for the complete evidence contract and troubleshooting boundary.

External participants should receive the repository URL and the
[`External Developer Dry Run`](docs/development/external-developer-dry-run.md)
runbook. Its evidence template is intentionally blank until an actual session.
The founder-accepted PRE-SEED result is recorded in the
[`2026-10-08 external dry-run evidence`](docs/evidence/2026-10-08-external-developer-dry-run.md).

The historical release-candidate state and subsequent release outcome are
documented in the
[`0.1.0-rc.1 evidence pack`](docs/releases/software-preview-0.1.0-rc.1.md),
with capability-level links in the
[`software evidence index`](docs/evidence/software-evidence-index.md).

## License

HIYELX is licensed under the
[`Apache License 2.0`](LICENSE). The package declares the SPDX expression
`Apache-2.0`, and the clean-install gate verifies that built wheels carry both
the expression and the canonical license text.

The CLI uses the generated Motor gRPC client over an ephemeral IPv4 loopback
port. Simulation time advances explicitly inside the owned `SimulatedMotor`;
there is no simulation-control RPC, wall-clock stepping, hardware access, or
cloud dependency.

## Module/Driver SDK Alpha

Current `main` contains post-release Module/Driver SDK Alpha work that is not
part of the `v0.1.0` release snapshot. Evaluate this alpha from repository
source; it has not been published to PyPI or another package registry, and no
compatibility guarantee is made. HCA-VERSION-1 selected package identity
`0.2.0a1` for current `main`. A possible future `v0.2.0a1` tag has not been
created, no new GitHub release or registry publication exists, and stable
`0.2.0` remains reserved for a later acceptance decision.

Trusted external motor packages can integrate without editing HIYELX core by
using the public, explicit `register_motor_driver` helper. Configuration never
imports Python paths or discovers packages. See the
[`Module/Driver SDK Alpha`](docs/development/module-driver-sdk.md) guide for the
strict settings, software-only compliance, `Motor` implementation, and
application-owned registration contract. The
[`Motor Driver Porting Checklist`](docs/development/motor-driver-porting-checklist.md)
defines the separate software and physical evidence boundaries. Generate a
non-overwriting, hardware-free starting point with:

```bash
hiyelx scaffold motor-driver ./acme-driver \
  --package-name acme_motor_driver \
  --model-name motor.acme.reference
```

Verify that the generated project builds as an independent wheel and runs
non-editably beside the HIYELX wheel through Runtime Manager and loopback gRPC:

```bash
uv run python scripts/verify_external_driver_install.py
```

The automated verifier is software packaging evidence only; by itself it is
not human-usability or physical-hardware acceptance. The separate HCA-SDK-5
external participant session was founder-accepted on 2026-10-12 at commit
`9e4e1f9615da75bd4be6717277e36b8cab85542b`. Its sanitized evidence and bounded
limitations are recorded in the
[`Module/Driver SDK external dry-run evidence`](docs/evidence/2026-10-12-module-driver-sdk-external-dry-run.md).

HCA-SDK-5 closes only the bounded external usability gate for the local-wheel
alpha workflow. HCA-HW-0 is now the active software-side hardware-readiness
task. Its strict, device-free preflight and fake-verifiable cleanup harness are
documented in
[`Hardware acceptance readiness`](docs/hardware/hardware-acceptance-readiness.md).
XL430 physical acceptance, real reference-driver physical acceptance, and
Physical Hardware Proof remain pending; Runtime Operations Alpha remains after
the hardware-readiness boundary.

## Pre-seed scope

- Resource / Component / Service model
- Motor API and hardware abstraction layer
- Deterministic simulation backend
- At least one real reference driver
- Versioned YAML/JSON configuration with Pydantic validation
- Model registry and module loading baseline
- Dependency DAG and lifecycle management
- gRPC / Protocol Buffers API
- Health, fault handling, graceful shutdown and safe-stop baseline
- Structured logging and observability baseline
- Python SDK / examples / developer documentation

## Engineering principles

1. Stable abstraction before features.
2. Config is topology.
3. Everything operational is observable.
4. Dependency order matters.
5. Simulation is a first-class backend.
6. Safety boundaries are explicit.
7. Measure before rewriting Python paths in another language.
8. Local-first, cloud-ready.
9. Extensibility must not require core edits.
10. Every release closes with a demonstrable capability.

## Canonical stack

- Python 3.12
- asyncio
- Pydantic
- gRPC + Protocol Buffers
- uv
- Ruff
- Pyright
- pytest + pytest-asyncio
- GitHub + GitHub Actions
- Codex for repo-aware engineering
- Supabase for future cloud/control-plane services, never as a runtime dependency

## Product boundary

The PRE-SEED runtime does **not** attempt to build a cloud SaaS, general-purpose SLAM/navigation, a certified functional-safety stack, hard real-time servo control in Python user space, or a foundation AI model.

## Repository direction

```text
src/hiyelx/
  runtime/
  config/
  resources/
  components/
  services/
  modules/
  rpc/
  telemetry/
  simulation/
  safety/
proto/
configs/
examples/
tests/
  unit/
  integration/
  simulation/
  hardware/
docs/
  architecture/
  decisions/
  development/
```

## Source-of-truth rule

- Product and architecture plan: `docs/plans/HIYELX_PRESEED_Master_Plan_v3.0.docx`
- Architecture decisions: `docs/decisions/`
- Implementation and CI: GitHub `main`
- Delivery state: `PRESEED.md`
- Optional coordination: Linear may be used when helpful, but is not a PRE-SEED dependency

HIYELX is currently focused on proving a production-quality robot runtime before expanding into motion, perception, autonomy, fleet, or cloud capabilities.
