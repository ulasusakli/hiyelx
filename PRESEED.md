# HIYELX PRE-SEED Founder Mode

## North Star

> Change the hardware, not the application.

HIYELX must expose stable application-level resource APIs that behave the same
against deterministic simulation and real hardware. Hardware selection belongs
behind the hardware abstraction layer (HAL), not in application code.

## Canonical master plan

The maintained program plan is
`docs/plans/HIYELX_PRESEED_Master_Plan_v3.0.docx`. It is the scheduling,
decision-gate, testing, and launch-readiness companion to this operational
NOW/NEXT/DONE file. Version 3.0 supersedes the prior standalone plan.

## Working model

PRE-SEED optimizes for time-to-working-product. Active capability work uses
NOW, NEXT, and DONE. A separately evidenced external gate may be marked
DEFERRED without treating it as complete:

### NOW

**HCA-HW-0 — hardware acceptance readiness**

The published `v0.1.0` Software Developer Preview remains the bounded release
snapshot at commit `e3801ed43ec4b173dae765ac583055314defce50`. Current `main`
contains later Module/Driver SDK Alpha software evidence under package identity
`0.2.0a1`. Do not imply that this work is part of `v0.1.0` or has been
published to a package registry. A possible future `v0.2.0a1` tag and release
require separate authorization; stable `0.2.0` remains reserved.

HCA-SDK-5 external usability acceptance remains complete. HCA-HW-0 is active:
establish the typed, explicit-opt-in, device-free preflight and fake-verifiable
acceptance sequence before approving any physical bench session. No Runtime
Operations Alpha work opens before this hardware-readiness boundary is
resolved.

### NEXT

1. Review HCA-HW-0 software readiness, then select and procure the exact motor,
   adapter, power, wiring, operator, and physical acceptance owner.
2. Run a separately authorized physical acceptance session; XL430 or an
   alternative reference driver remains pending until that evidence is
   reviewed.
3. Open Runtime Operations Alpha only after the hardware-readiness boundary is
   resolved.

### DONE

- Repository initialized.
- PRE-SEED product boundary, technical thesis, and canonical stack documented.
- Founder Mode workflow established.
- Canonical source baseline established and synchronized with GitHub on
  2026-10-06.
- Canonical workspace consolidated under `hiyelx`; PRE-SEED Master Plan v3.0
  established as the active program plan.
- Minimal Python Foundation established; the quality gate passes.
- Resource Core established with stable identity, explicit deterministic
  lifecycle transitions, inspectable vendor-neutral health, and tested failure
  paths.
- Motor API plus deterministic simulation established with vendor-neutral
  commands and state, explicit simulated time, and lifecycle-guarded control.
- Configuration plus Model Registry established with strict versioned local
  documents, explicit instance-local registration, and lifecycle-free factory
  creation.
- Runtime Manager established with deterministic dependency planning, exclusive
  local ownership, sequential startup, rollback, lookup, and reverse shutdown.
- gRPC Boundary established with a versioned local Motor service, centralized
  domain status mapping, loopback-only transport ownership, and a real async
  client/server integration proof.
- RB-1 Operation Deadlines + Fault Visibility established with immutable
  per-resource deadline policy, typed timeout/backend failures, safe health
  summaries, serialized late blocking-call completion, and stable gRPC status
  mapping.
- RB-2 Safe-Stop + Health + Local Structured Events established with ordered
  best-effort motor stop, typed cleanup outcomes, vendor-neutral health
  degradation, and deterministic instance-local records.
- Reliability Baseline established across RB-1 and RB-2 without adding remote
  telemetry, automatic recovery, or hardware acceptance claims.
- DX-1 Developer Experience + Repeatable SIM Demo established with an
  installable CLI, canonical configuration validation, deterministic explicit
  simulation time, generated-client loopback gRPC control, and verified cleanup.
- DR-1 Clean Install + Demo Evidence established with a canonical transcript,
  isolated non-editable wheel installation, source-import rejection, fresh
  Python 3.12 execution, and a bounded CI packaging smoke gate.
- EDR-1 External Developer Dry Run accepted by the founder on 2026-10-08 at
  commit `32e47a0`, with an exact SIM transcript and passing clean non-editable
  wheel installation. Evidence limitations are recorded in
  `docs/evidence/2026-10-08-external-developer-dry-run.md`.
- LIC-1 Apache-2.0 License Integration established with canonical repository
  text, PEP 639 package metadata, and deterministic wheel license verification.
- Software Developer Preview authorized and published as GitHub pre-release
  `v0.1.0`, targeting commit
  `e3801ed43ec4b173dae765ac583055314defce50`; no PyPI or other package-registry
  publication occurred.
- HCA-SDK-1/HCA-SDK-2 integrated at
  `29551e1262e85fa0ca0c6c4a5278d64d47eef8d0`, establishing explicit external
  motor-driver registration, strict driver-owned settings validation, and a
  non-overwriting hardware-free scaffold.
- HCA-SDK-3 integrated at
  `003e765862aa2c847b0c2224e2d9748a3cdc0b8f`, adding the deterministic
  software-only Motor compliance harness and porting checklist.
- HCA-SDK-4 integrated at
  `d1cfb3d083836c207864c1c84e01787a9db78294`, proving an independently
  buildable external-driver wheel, clean non-editable installation,
  source-tree import rejection, and configuration to explicit registry to
  Runtime Manager to loopback gRPC to Motor execution.
- HCA-VERSION-1 selected `0.2.0a1` as the post-`v0.1.0` HIYELX package
  identity. Generated external drivers remain independently versioned at
  `0.1.0` and pin `hiyelx==0.2.0a1`. No tag, release, registry publication,
  compatibility guarantee, or physical acceptance is created by this
  alignment.
- HCA-SDK-5 was founder-accepted and closed on 2026-10-12 from an external
  human participant session at
  `9e4e1f9615da75bd4be6717277e36b8cab85542b`. Codex served as an
  execution/support tool, not the participant. The founder approved the
  participant's `SUBSTANTIAL` prior-exposure exception. Fresh-clone SHA
  equality, interactive zsh validation, the exact six-file scaffold, five
  generated tests, Ruff, Pyright, both wheel builds, clean imports, and all
  five external-driver verifier signals passed with 0 assistance requests,
  0 interventions, and 0 environment blockers in 22 minutes 48 seconds.
  Evidence is recorded in the
  [`HCA-SDK-5 evidence record`](docs/evidence/2026-10-12-module-driver-sdk-external-dry-run.md).
  This closes external SDK usability only; it does not close XL430 or real
  reference-driver physical acceptance or Physical Hardware Proof.

### DEFERRED

**Physical Hardware Proof**

The fixed DYNAMIXEL XL430-W250-T driver implementation remains ready for its
documented opt-in bench acceptance on model 1060 over Protocol 2.0 at 57,600
baud. Real-driver physical acceptance is incomplete, and no physical validation
claim exists. Software verification is not physical acceptance. The Real
Reference Driver and full PRE-SEED hardware milestone remain incomplete until
that external evidence exists.

Physical Hardware Proof remains deferred and separately evidenced.

The software-only HCA-HW-0 readiness boundary is documented in
[`docs/hardware/hardware-acceptance-readiness.md`](docs/hardware/hardware-acceptance-readiness.md).
Its blank evidence template does not represent a completed physical session.

## Minimum quality gate

Every change must pass locally before it is considered done:

```bash
uv run ruff check .
uv run pyright
uv run pytest
```

The CI workflow mirrors this gate. CI is intentionally small; it is a fast
verification loop, not a release-management system.

## Processes removed for PRE-SEED

The following are not mandatory while HIYELX is in Founder Mode:

- Linear issues or GitHub issues for every change
- Feature branches and pull requests for every change
- Multi-stage or release-oriented CI/CD
- Sprint ceremonies, story points, labels, and heavyweight status workflows
- ADRs for routine, reversible implementation decisions

Issues, branches, pull requests, and ADRs may still be used when they reduce
risk or clarify a consequential decision. They are tools, not gates.

## Milestones

1. **Foundation** — Python 3.12 package, uv environment, quality gate, minimal CI.
2. **Resource Core** — identity, lifecycle, health, and failure contracts.
3. **Motor API + Simulation** — vendor-neutral API and deterministic simulated motor.
4. **Configuration + Model Registry** — validated topology and pluggable model lookup.
5. **Runtime Manager** — dependency graph, ordered startup, shutdown, and ownership.
6. **gRPC Boundary** — external process commands an actuator and reads state.
7. **Real Reference Driver** — one real backend with simulation/real API parity.
8. **Reliability Baseline** — faults, timeouts, safe-stop, structured logs, and health.
9. **PRE-SEED Demo** — the same client runs unchanged against simulated and real hardware.

## Scope boundary

PRE-SEED does not include cloud/SaaS product work, Supabase integration,
general-purpose autonomy, hard real-time control in Python user space, or a
certified functional-safety claim.
