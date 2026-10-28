# HIYELX

HIYELX is a hardware-independent robotics software platform for building, running, and operating intelligent machines through stable resource APIs, configuration-driven topology, pluggable hardware models, and a local-first robot runtime.

## Current stage

**PRE-SEED — Runtime Operations Alpha, RTO-1 through RTO-4 complete**

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
alpha workflow. HCA-HW-0 software readiness was completed at
`535c14cfc9ec1cc819bb86d4ddf31a9d7fe82569`. Its strict, device-free preflight
and fake-verifiable cleanup harness are documented in
[`Hardware acceptance readiness`](docs/hardware/hardware-acceptance-readiness.md).
XL430 physical acceptance, real reference-driver physical acceptance, and
Physical Hardware Proof remain pending in parallel and require separate
evidence.

## Runtime Operations Alpha

RTO-1 was completed at `bee98b6c48725db2e9311b30fcf8f00126f6061e`.
It provides immutable deterministic snapshots of one local Runtime Manager,
ordered resource lifecycle and health state, startup ownership, and structured
instance-local events.

RTO-2 Local Runtime Process Control, RTO-3 Local Events, Run History, and
Explicit Retention, and RTO-4 Runtime Operations Alpha Acceptance are complete
on current `main`. Start the canonical simulation runtime in one terminal:

```bash
hiyelx runtime start examples/configs/sim-motor.yaml --session local-sim
```

Then inspect and stop it from another terminal:

```bash
hiyelx runtime status --session local-sim
hiyelx runtime runs list
hiyelx runtime runs list --json
```

Copy the canonical run ID from `runs list`, then inspect the incomplete active
run and its committed event prefix:

```bash
hiyelx runtime runs show RUN_ID
hiyelx runtime events --run RUN_ID
hiyelx runtime events --run RUN_ID --after 3 --limit 1000
hiyelx runtime events --run RUN_ID --json
hiyelx runtime stop --session local-sim
```

After the foreground owner exits, the same run and event commands read the
durable local SQLite history. Retention is explicit and never automatic:

```bash
hiyelx runtime runs show RUN_ID --json
hiyelx runtime events --run RUN_ID --limit 1
hiyelx runtime runs prune --keep 20
```

The foreground owner uses a private current-user Unix socket and a strict
versioned local protocol. Ephemeral control state is separate from the durable
current-user SQLite history. It accepts built-in simulation models only; it
does not bind TCP, discover hardware, load arbitrary modules, upload telemetry,
or require a cloud/control plane. There is no automatic retention, migration,
repair, crash classification, or background service. See the
[`Runtime Operations Alpha`](docs/architecture/runtime-operations-alpha.md)
contract for storage ownership, query/prune ordering, failure precedence,
cleanup, and exit codes.

Verify the complete non-editable installed-wheel Runtime Operations Alpha
journey with:

```bash
uv run python scripts/verify_clean_install.py
```

RTO-3 Slices A, B, C1, and C2 are integrated and accepted. The C2
implementation and acceptance commit is
`c40a66d4360272070403d14b9341ad95c455ad07`; the runner-portability commit is
`7c402a4be4468d3e9501a8035c8df5a7d285676f`. The
[`39493825893` Quality gate](https://github.com/ulasusakli/hiyelx/actions/runs/39493825893)
tested that exact portability commit and passed both hosted jobs:

- Ubuntu: Ruff passed, Pyright reported `0 errors, 0 warnings`, pytest reported
  `621 passed, 1 skipped`, and the clean installed-wheel journey passed. The
  one skip was the explicitly unselected physical XL430 acceptance test; it
  was not counted as passing.
- macOS: the standard GitHub-hosted `macos-15-intel` runner provided macOS 15
  on Intel/x86_64; all 296 focused tests, the clean installed-wheel RTO-3
  journey, and artifact cleanup passed.

RTO-4 adds no production runtime behavior or public API. It closes
software/runtime acceptance for the integrated RTO-1 through RTO-3 behavior
through installed-wheel automation, hosted portability, and one founder
black-box session. The automated matrix was integrated at
`f4284c01dda9a35aec38979a356ffb6b9c02067b`. Quality gate
[`40067721268`](https://github.com/ulasusakli/hiyelx/actions/runs/40067721268)
tested that exact SHA:

- Ubuntu job `120794370547` passed Ruff, strict Pyright, `647 passed, 1`
  physical XL430 test explicitly skipped, and the exact 21-line installed-wheel
  result with all 12 RTO-4 markers ending
  `rto4-automated-acceptance=passed`.
- GitHub-hosted macOS job `120794370479` used `macos-15-intel` on Intel/x86_64
  and passed 322 focused tests plus the same exact 21-line installed-wheel
  result and 12-marker registry.

The founder black-box evidence was integrated at
`2538398437b2438f20c6d78b6d9369221696581f`. Quality gate
[`40086361304`](https://github.com/ulasusakli/hiyelx/actions/runs/40086361304)
passed Ubuntu job `120850006494` and macOS Intel job `120850006684` on that
exact SHA. The founder completed `8/8` steps in `00:06:30` with zero assistance
requests, blockers, unexpected leaks, live-process leftovers, or task-owned
artifact leftovers and recorded `ACCEPT`. See the
[`RTO-4 founder acceptance evidence`](docs/evidence/2026-10-24-rto4-founder-acceptance.md).

## Simulation/Preview Alpha

Runtime Operations Alpha is complete. SIM-P0 through SIM-P3 Simulation/Preview
Alpha software scope is complete on current `main`. SIM-P3 was
accepted through the Founder Interpretation Attestation Route; original failed
zero-assistance live attempts remain failed and were not reclassified. The
contract amendment and sanitized attestation evidence were integrated at
`a26195494f617ff32574966f491426d3e9f0d26b`; Quality gate
[`40736962525`](https://github.com/ulasusakli/hiyelx/actions/runs/40736962525)
passed both hosted jobs:

- Ubuntu job `122987995604`: `705 passed, 1 physical skipped`.
- GitHub-hosted macOS Intel job `122987996143`: `macos-15-intel`, Intel/x86_64,
  `365 passed`.
- Both produced the exact 29-line installed-wheel result, all `8/8` SIM
  markers, and final `sim-preview-acceptance=passed`.

See the [SIM-P3 founder contract](docs/architecture/simulation-preview-founder-acceptance.md)
and [accepted founder attestation](docs/evidence/2026-10-28-sim-p3-founder-attestation.md).
The founder's local Darwin/arm64 evidence is not hosted ARM64 portability
evidence. Next is `STUDIO-P0 — Studio Lite observational contract`; Studio Lite
implementation has not started. Physical acceptance remains separate and
pending. Package `0.2.0a1`, tag, release, and publication state are unchanged.

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
