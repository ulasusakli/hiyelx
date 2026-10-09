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

**Software Preview Release Candidate**

The versioned `0.1.0-rc.1` candidate pack and software evidence index are under
final review. The founder-authorized Apache License 2.0 decision is implemented
in the repository and package evidence. Separate founder release authorization
remains outstanding. Do not add runtime, cloud, or hardware capability, and do
not mark the Software Developer Preview released.

### NEXT

Close the Software Preview Release Candidate before opening the Software
Developer Preview. Physical Hardware Proof remains a separate deferred gate and
is still required before the full PRE-SEED milestone can close.

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

### DEFERRED

**Physical Hardware Proof**

The fixed DYNAMIXEL XL430-W250-T driver implementation remains ready for its
documented opt-in bench acceptance on model 1060 over Protocol 2.0 at 57,600
baud. No physical acceptance was performed for RB-1. The Real Reference Driver
milestone is not closed until that external evidence exists.

The Software Developer Preview may proceed using the accepted software
evidence. The full PRE-SEED milestone remains incomplete until the separately
evidenced physical hardware gate is complete.

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
