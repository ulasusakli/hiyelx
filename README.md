# HIYELX

HIYELX is a hardware-independent robotics software platform for building, running, and operating intelligent machines through stable resource APIs, configuration-driven topology, pluggable hardware models, and a local-first robot runtime.

## Current stage

**PRE-SEED — v0.1 Robot Runtime**

The current objective is to prove the core technical thesis:

> Change the hardware, not the application.

The same application-level API should run against deterministic simulation and at least one real hardware driver, with hardware selection resolved through configuration and the model registry.

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

- Product and architecture: HIYELX Product & Technical Master Plan
- Architecture decisions: `docs/decisions/`
- Implementation and CI: GitHub
- Delivery state: Linear

HIYELX is currently focused on proving a production-quality robot runtime before expanding into motion, perception, autonomy, fleet, or cloud capabilities.
