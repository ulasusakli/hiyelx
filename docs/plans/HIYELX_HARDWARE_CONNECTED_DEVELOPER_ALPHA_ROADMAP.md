# HIYELX Hardware-Connected Developer Alpha Roadmap

**Program start:** 9 October 2026  
**Target HCA release:** 18 December 2026  
**Operating model:** Founder Mode; one founder plus Codex  
**Status:** HCA-0 in progress; HCA-2 first slice started early while HCA-1
hardware procurement remains external

## Outcome

The Hardware-Connected Developer Alpha (HCA) proves the HIYELX product thesis
with a real, physically accepted reference device:

> A developer validates and runs one application against deterministic
> simulation and an accepted XL430 backend without changing the
> application-level Motor API.

HCA is a local-first developer product. It is not a finished robot, a 3DOF arm,
a cloud control plane, a hard-real-time controller, or a certified functional
safety system.

## Planning assumptions

- The canonical repository remains `ulasusakli/hiyelx` on `main`.
- Python 3.12 remains the supported runtime for HCA.
- One secured, unloaded XL430-W250-T bench kit is available by 13 October 2026.
- A physical power cutoff is accessible during every hardware run.
- Physical movement requires a separate explicit run authorization at the time
  of the test; this roadmap does not itself authorize motor movement.
- The team remains one founder plus Codex. Hardware or founder availability
  delays move the affected external gate rather than creating false evidence.
- Founder Mode stays lightweight: no mandatory issue tracker, PR ceremony, or
  release pipeline expansion.

## HCA delivery schedule

| Phase | Dates | Deadline | Deliverable | Exit gate |
|---|---|---|---|---|
| HCA-0 — Baseline and product contract | 9–12 Oct 2026 | 12 Oct | Current-state audit, roadmap, scope and evidence contract | Baseline is reproducible; physical and software claims are separated |
| HCA-1 — XL430 physical proof | 13–23 Oct 2026 | 23 Oct | Bounded bench acceptance and evidence record | Opt-in test passes on model 1060; cleanup and torque-off checks are recorded |
| HCA-2 — Module/Driver SDK Alpha | 26 Oct–13 Nov 2026 | 13 Nov | Driver authoring contract, scaffold, compliance tests and example module | A sample driver integrates without editing HIYELX core |
| HCA-3 — Runtime Operations Alpha | 16–27 Nov 2026 | 27 Nov | Supported run/inspect/stop workflow and operator diagnostics | A user can start, inspect, stop and diagnose the runtime predictably |
| HCA-4 — Simulation/Preview Alpha | 30 Nov–11 Dec 2026 | 11 Dec | Deterministic scenario and parity workflow | The same user journey is demonstrated in SIM and accepted REAL backends |
| HCA-5 — External developer acceptance and HCA release | 14–18 Dec 2026 | 18 Dec | Fresh-machine dry run, evidence pack and bounded alpha release decision | External user completes the documented workflow; founder makes release decision |

## Phase details

### HCA-0 — Baseline and product contract

**Goal:** Turn the released software preview into an executable physical-alpha
program without broadening the product prematurely.

Deliverables:

- Verify branch, clean worktree, local HEAD, `origin/main`, and live GitHub
  `main` before implementation.
- Re-run the non-hardware quality baseline and report pass, fail, skip,
  deselected, and environment-blocked categories separately.
- Record the live `v0.1.0` Software Developer Preview as the starting baseline.
- Prepare a separate repository documentation-sync change; do not rewrite
  release history.
- Freeze HCA scope and acceptance language.
- Produce the physical bench readiness checklist and evidence template.

Exit criteria:

- Software baseline is green or every deviation is explained.
- No physical acceptance is claimed.
- HCA-1 has an exact kit, operator checklist, command, evidence template, and
  explicit authorization boundary.

### HCA-1 — XL430 physical proof

**Goal:** Close the deferred Real Reference Driver physical acceptance gate.

Deliverables:

- Confirm the fixed bench kit: XL430-W250-T TTL, U2D2, Power Hub, regulated
  12 V / 5 A supply, model 1060, Protocol 2.0, ID 1, and 57,600 baud.
- Confirm an unloaded secured actuator and reachable physical power cutoff.
- Perform a no-motion connectivity preflight before enabling torque.
- Run the existing explicitly opted-in physical acceptance path only after
  separate founder authorization.
- Record command/state observations, cleanup result, torque-disabled manual
  check, environment, commit SHA, and operator.
- Re-run the software quality gate after the evidence change.

Exit criteria:

- The real Runtime Manager and loopback gRPC path identify and control the
  accepted motor within the documented movement bounds.
- Positive velocity, stop, negative velocity, stop, state reads, transport
  stop, runtime shutdown, and final torque-disabled check are evidenced.
- Failures, skips, and inconclusive runs remain visible; a failed or unrun bench
  procedure cannot close the gate.

### HCA-2 — Module/Driver SDK Alpha

**Goal:** Let a developer add a hardware module without modifying HIYELX core.

Deliverables:

- Define the supported module boundary and stable registration contract.
- Provide a minimal driver scaffold and packaging example.
- Provide deterministic fake-transport and lifecycle test utilities.
- Add a driver compliance suite covering identity, settings validation,
  lifecycle, command/state behavior, error sanitization, deadlines, cleanup,
  and SIM/REAL application-level parity.
- Document versioning, compatibility, and unsupported dynamic-loading behavior.
- Demonstrate one sample external module using explicit registration.

Exit criteria:

- The sample module installs and registers without a HIYELX core edit.
- It passes the compliance suite and deterministic example workflow.
- Configuration cannot import arbitrary code; registration remains explicit.

### HCA-3 — Runtime Operations Alpha

**Goal:** Make the local runtime operable as a product, not only as a test
fixture.

Deliverables:

- A supported CLI path to validate configuration and run the local runtime.
- Predictable process signal handling and ordered shutdown.
- Readable topology, lifecycle, health, fault, and local-event inspection.
- Clear distinction between normal stop, best-effort safe-stop, and physical
  emergency power removal.
- Bounded diagnostics that do not expose device paths, credentials, raw backend
  exceptions, or arbitrary device data to clients.

Exit criteria:

- A developer can start, inspect, stop, and diagnose one configured system from
  documented commands.
- Failure paths preserve causes and deterministic cleanup ordering.
- No remote binding, authentication, TLS, recovery loop, watchdog, or certified
  safety claim is introduced accidentally.

### HCA-4 — Simulation/Preview Alpha

**Goal:** Turn deterministic simulation into a repeatable preview service for
the hardware-connected workflow.

Deliverables:

- Versioned deterministic scenarios for normal and bounded failure paths.
- A machine-readable final state and event summary.
- A documented SIM-to-REAL parity checklist.
- Preview output suitable for later Studio consumption without coupling the
  runtime to a UI or cloud service.

Exit criteria:

- The same application-level client journey is demonstrated against SIM and
  the accepted REAL reference backend.
- Scenario results are deterministic and testable.
- Preview adds no hardware claim beyond HCA-1 evidence.

### HCA-5 — External developer acceptance and HCA release

**Goal:** Prove that a developer other than the implementation agent can use
the product from documented inputs.

Deliverables:

- Fresh Python 3.12 non-editable installation.
- External developer runbook covering SIM, runtime operations, driver SDK, and
  the separately controlled REAL handoff.
- Evidence record with timing, confusion points, failures, interventions, and
  unresolved limitations.
- HCA evidence index and founder release-decision report.

Exit criteria:

- The external developer completes the supported workflow without hidden
  repository knowledge.
- All required software gates pass.
- Physical proof is linked, not generalized.
- Founder explicitly authorizes or rejects the HCA release operation.

## Post-HCA product roadmap

| Product phase | Target dates | Deadline | User outcome |
|---|---|---|---|
| Studio Lite | 4–29 Jan 2027 | 29 Jan | Configure, start, stop, and inspect a local robot through a minimal UI |
| Camera/Vision Foundation | 1–26 Feb 2027 | 26 Feb | Use a hardware-neutral Camera resource, timestamps, calibration, stream lifecycle, simulation, and replay |
| Shared Bus + Multi-Axis Motion | 1 Mar–9 Apr 2027 | 9 Apr | Own multiple motors on one DYNAMIXEL bus and execute bounded joint/group commands |
| 3DOF Reference Demo | 12–30 Apr 2027 | 30 Apr | Run one documented 3DOF application in simulation and on a measured physical reference arm |
| Autonomy Alpha | 3 May–11 Jun 2027 | 11 Jun | Compose perception and motion into local task/state-machine behaviors |
| Seed Readiness Review | 14–18 Jun 2027 | 18 Jun | Decide whether evidence supports team, ecosystem, fleet, and cloud expansion |

## Hard dependencies and schedule risks

1. **Hardware availability:** HCA-1 cannot close without the exact secured bench
   kit and an authorized operator session.
2. **Shared-bus ownership:** The current reference driver supports one actuator
   per serial port. A credible 3DOF demo depends on an explicit shared-bus and
   multi-motor ownership design; it is not part of HCA.
3. **Safety boundary:** Software stop is not an emergency stop. Hardware runs
   require accessible physical power removal and a controlled procedure.
4. **Scope pressure:** Studio, vision, motion, autonomy, and cloud work must not
   delay the physical parity proof, Driver SDK, or core runtime operability.
5. **Single-founder capacity:** A missed external gate shifts downstream dates.
   Evidence must not be weakened to preserve a calendar date.

## HCA release contents

- Local-first HIYELX Runtime
- Python 3.12 SDK and CLI
- Module/Driver SDK Alpha and compliance tests
- Deterministic simulation and preview workflow
- Physically accepted XL430 reference backend
- Loopback-only gRPC Motor boundary
- Runtime health, fault, local-event, shutdown, and best-effort safe-stop baseline
- Installation, integration, bench, and external developer documentation
- Evidence index with software, external-developer, and physical evidence kept
  separate

## Explicitly out of HCA scope

- 3DOF or multi-axis product claims
- Shared DYNAMIXEL bus support unless separately authorized
- Camera/Vision, Motion planning, or Autonomy implementation
- Cloud/SaaS, fleet management, accounts, remote control, or remote telemetry
- Internet-facing gRPC, authentication, authorization, or TLS
- Automatic retry, reconnect, recovery, watchdog, or hardware emergency stop
- Hard-real-time guarantees or certified functional safety
- PyPI or other package-registry publication

## Current action

HCA-0 starts with a read-only audit of the current XL430 driver, physical test,
hardware runbook, module registration boundary, Runtime Manager, and quality
baseline. No physical I/O or motor movement is authorized by this action.

Hardware procurement is now founder-owned. HCA-1 remains an open external gate,
but software work proceeds in parallel. The 18 December 2026 HCA release target
is conditional on physical evidence being available by 30 November 2026; the
evidence standard will not be reduced to protect the date.

## HCA-0 execution log — 9 October 2026

- Canonical checkout: `/Users/ulas/Documents/hiyelx`
- Branch: `main`
- Local `HEAD`: `e3801ed43ec4b173dae765ac583055314defce50`
- Local `origin/main`: `e3801ed43ec4b173dae765ac583055314defce50`
- Live GitHub `main`: `e3801ed43ec4b173dae765ac583055314defce50`
- GitHub `v0.1.0` release: present and marked pre-release
- Worktree: clean
- `uv lock --check`: PASS; 23 packages resolved
- Proto consistency: PASS
- Ruff: PASS
- Pyright: PASS; 0 errors, 0 warnings
- Pytest: PASS; 244 passed, 1 opt-in physical test skipped
- Failed: 0
- Deselected: 0
- Environment-blocked: 0
- Physical I/O performed: no
- Motor movement authorized or performed: no

Audit finding: the existing physical acceptance path is already bounded and
explicitly opted in, but HCA-1 still needs a dated bench-readiness checklist,
an evidence record template, and a separate founder authorization before the
hardware command is run.

## HCA-2 early-start log — 9 October 2026

The first Module/Driver SDK vertical slice was implemented locally in the
canonical repository without physical I/O:

- Added a public explicit `register_motor_driver` helper.
- Added strict driver-settings validation through a driver-owned Pydantic model.
- Added a runtime check that external builders return the `Motor` contract.
- Migrated the existing XL430 registration path to the public SDK helper while
  preserving its factory and transport seams.
- Added an external-driver integration proof through configuration, Runtime
  Manager, and loopback gRPC without a HIYELX core edit.
- Added the Module/Driver SDK Alpha authoring guide.
- Full verification: 250 passed, 1 opt-in physical test skipped, 0 failed,
  0 deselected, 0 environment-blocked; Ruff and Pyright passed.
- Clean non-editable wheel installation passed, and the built wheel contains
  the new `hiyelx.sdk` package.

The slice remains an uncommitted local change pending review. HCA-SDK-2 below
adds the scaffold and baseline generated tests; a mature reusable third-party
compliance suite remains later work.

## HCA-SDK-2 execution log — 9 October 2026

The Driver SDK alpha now includes a safe generated starting point:

- Added `hiyelx scaffold motor-driver OUTPUT --package-name ... --model-name ...`.
- The command refuses every existing target and never overwrites user files.
- Rendering occurs in a temporary sibling followed by an atomic rename.
- The generated package is hardware-free and includes strict settings,
  explicit registration, an in-memory Motor implementation, example config,
  pytest configuration, and five baseline contract tests.
- Generated tests cover construction without I/O, invalid settings, lifecycle,
  command/state, stop, and shutdown.
- A generated driver was verified through configuration, Runtime Manager, and
  loopback gRPC.
- The installed-wheel clean-install gate now creates and checks the complete
  six-file scaffold layout.
- Full verification: 264 passed, 1 opt-in physical test skipped, 0 failed,
  0 deselected, 0 environment-blocked; Ruff and Pyright passed.
- Generated-scaffold verification: 5 passed; Ruff passed; Pyright passed.
- Clean non-editable wheel installation passed.

The generated contract tests are a baseline, not complete vendor-driver
certification. Transport serialization, injected transport failures, deadlines,
cleanup ordering, physical opt-ins, and SIM/REAL parity remain explicit work for
each concrete driver and later SDK compliance slices.
