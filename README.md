# HIYELX

HIYELX is a hardware-independent robotics software platform for building, running, and operating intelligent machines through stable resource APIs, configuration-driven topology, pluggable hardware models, and a local-first robot runtime.

## Current stage

**PRE-SEED — v0.1 Robot Runtime**

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

The CLI uses the generated Motor gRPC client over an ephemeral IPv4 loopback
port. Simulation time advances explicitly inside the owned `SimulatedMotor`;
there is no simulation-control RPC, wall-clock stepping, hardware access, or
cloud dependency.

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
