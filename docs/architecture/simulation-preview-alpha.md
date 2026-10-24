# Simulation/Preview Alpha — SIM-P0 Preview Contract

> - **Status:** Accepted / Frozen — SIM-P0
> - **Founder approval:** `APPROVE SIM-P0 CONTRACT DEFAULTS`
> - **Approval date:** `2026-10-24`
> - **Evidence baseline:** `6237fa8ce9ec6eaaa44bb6b6b505dd57c82a3073`
> - **Package version:** `0.2.0a1`
> - **Runtime prerequisite:** RTO-1 through RTO-4 accepted
> - **Preview implementation:** Not started
> - **Studio/UI implementation:** Not started
> - **Contract integration:** This bounded docs-only commit
> - **Physical hardware acceptance:** Separate and pending

Normative words such as **must** and **must not** describe the founder-approved
contract. They do not claim that the preview behavior is implemented. The
contract is frozen by the approval recorded above; repository integration
remains a separate bounded step.

## 1. Purpose

SIM-P0 defines the first application-facing Simulation/Preview contract for
HIYELX. Its product outcome is deliberately small:

> A person can inspect what one local deterministic simulation is doing now,
> through a stable read-only value model that a CLI or future Studio UI can
> render without importing drivers, reading private runtime files, or knowing
> hardware-specific details.

SIM-P0 is contract work. It does not add a new command, endpoint, runtime
operation, database table, protobuf message, browser screen, or physical
behavior. The next implementation slices must remain bounded by the contract
accepted here.

The preview is not a second runtime. It is a sanitized observation layer over
the existing local Runtime Manager, deterministic simulated resources, and
Runtime Operations state.

## 2. Why the contract precedes the UI

HIYELX already exposes enough isolated primitives to prove deterministic motor
simulation, but no single existing surface is a safe product preview:

- `MotorState` exposes angular position and angular velocity in SI units.
- `SimulatedMotor` changes position only through explicit `advance_time()` and
  never uses a wall clock, background task, or randomness.
- `RuntimeOperationsSnapshot` exposes immutable lifecycle, health, ordering,
  and sanitized event state.
- the local Motor gRPC service exposes motor reads and commands, but it does
  not expose simulation time, preview revision, runtime health, or a read-only
  preview boundary;
- the RTO-2 private control protocol exposes only `status` and `stop`; and
- RTO-3 SQLite history records runs and events, not a live component-state
  projection.

A UI built directly on any one of those surfaces would either be incomplete or
would couple the product to private implementation details. SIM-P0 therefore
freezes the renderer-neutral value contract before CLI or Studio work begins.

This contract was derived from the current operational plan and implementation:

- [`PRESEED.md`](../../PRESEED.md) and the
  [`PRE-SEED Master Plan`](../plans/HIYELX_PRESEED_Master_Plan_v3.0.docx);
- the accepted
  [`Runtime Operations Alpha`](runtime-operations-alpha.md) contract;
- the vendor-neutral [`Motor`](../../src/hiyelx/components/motor.py) state and
  command contract;
- the deterministic
  [`SimulatedMotor`](../../src/hiyelx/simulation/motor.py) implementation;
- the read-only
  [`RuntimeOperations`](../../src/hiyelx/runtime/operations.py) snapshot;
- the existing [`gRPC boundary`](grpc-boundary.md); and
- the private local owner
  [`control protocol`](../../src/hiyelx/runtime/control.py).

## 3. Existing evidence and exact gaps

| Area | Implemented at the baseline | Not yet implemented |
| --- | --- | --- |
| Motor state | Frozen `MotorState` with finite radians and radians/second. | Preview-specific state wrapper and canonical serialization. |
| Simulation | Explicit, deterministic piecewise-constant velocity integration. | Accumulated simulation time and a mutation revision counter. |
| Runtime observation | Frozen, ordered, sanitized RTO-1 snapshots. | Component state inside the runtime observation. |
| Cross-process owner | Private local session, status, stop, cleanup, and durable run/event history. | A read-only preview request and response. |
| RPC | Loopback Motor state plus command operations. | A read-only preview service contract and simulation metadata. |
| UI | None. | Studio preview screen, rendering, controls, accessibility, and usability evidence. |

The gaps in the final column are accepted work for later slices, not current
capabilities.

## 4. In scope

The accepted SIM-P0 contract will define:

- one immutable, versioned preview snapshot;
- a deterministic ordered collection of simulated motor projections;
- vendor-neutral resource identity, lifecycle, and health;
- angular position in radians and angular velocity in radians per second;
- explicit per-resource simulation time;
- a deterministic per-resource mutation revision;
- read-only and side-effect-free observation semantics;
- finite-number, ordering, sanitization, and size rules;
- a local-only application boundary for a future CLI and Studio adapter;
- error, cleanup, portability, and installed-wheel acceptance expectations;
- clear separation between current-state preview and future replay; and
- clear separation between software simulation and physical evidence.

The first implementation may support only the explicitly registered built-in
`motor.simulated` model. That is a bounded Alpha constraint, not a change to
the general Motor or external-driver contracts.

## 5. Explicitly out of scope

SIM-P0 and the first preview implementation must not claim or add:

- physical hardware, XL430, serial enumeration, discovery, transport opening,
  torque, or movement;
- a hardware-state preview or a simulation/hardware comparison;
- camera input, recording, playback, timeline scrubbing, or run replay;
- 2D or 3D geometry, collision, inertia, gravity, joint limits, or a physics
  engine;
- shared-bus, multi-axis coordination, a 3DOF arm, planning, or autonomy;
- runtime start, stop, command, or time-advance controls in the preview API;
- generic resource mutation or arbitrary method invocation;
- a new daemon, detached owner, scheduler, polling loop, or background sampler;
- remote binding, cloud/control-plane dependency, authentication, organization,
  or location models;
- telemetry upload, automatic retry, reconnect, or recovery;
- a new public protobuf surface during SIM-P0;
- direct Studio access to the private Unix socket or SQLite history database;
- hard-real-time, production-readiness, or certified-safety claims; or
- a package-version change, tag, release, registry publication, or compatibility
  guarantee.

## 6. Accepted domain contract

The first implementation must introduce frozen value objects equivalent to the
following renderer-neutral schema. The names and field allowlist are frozen by
SIM-P0 approval; repository integration does not itself implement them.

```python
@dataclass(frozen=True, slots=True)
class SimulationMotorPreviewState:
    angular_position_radians: float
    angular_velocity_radians_per_second: float
    simulation_time_seconds: float
    revision: int


@dataclass(frozen=True, slots=True)
class SimulationPreviewResourceSnapshot:
    identity: ResourceIdentity
    kind: Literal["motor"]
    lifecycle_state: LifecycleState
    health_status: HealthStatus
    health_summary: str | None
    state: SimulationMotorPreviewState


@dataclass(frozen=True, slots=True)
class SimulationPreviewSnapshot:
    schema_version: Literal["1"]
    runtime_state: RuntimeManagerState
    resources: tuple[SimulationPreviewResourceSnapshot, ...]
```

The contract intentionally does not expose a model name. `kind="motor"` is an
application concept; `motor.simulated`, a vendor driver, Python class names,
registry factories, and configuration settings remain composition details.

### 6.1 Field rules

| Field | Rule |
| --- | --- |
| `schema_version` | Exact string `"1"`. Booleans, integers, floats, and unknown versions are invalid at serialized boundaries. |
| `runtime_state` | Existing typed `RuntimeManagerState`; no backend-authored text. |
| `resources` | Immutable tuple in Runtime Manager startup-plan order. Identity is unique within the snapshot. |
| `identity` | Existing application-assigned `ResourceIdentity`; serialization uses its string value. |
| `kind` | Exact Alpha literal `"motor"`. Unknown kinds fail closed rather than being guessed. |
| `lifecycle_state` | Existing typed `LifecycleState`. |
| `health_status` | Existing typed `HealthStatus`. |
| `health_summary` | `None` or an existing fixed HIYELX sanitized summary; arbitrary backend text is omitted. |
| angular values | Finite IEEE-754 values in SI units. NaN and infinities are invalid. |
| `simulation_time_seconds` | Finite, non-negative, per-resource simulated time. It is not wall-clock time. |
| `revision` | Non-negative integer mutation counter. A boolean is invalid even though Python treats it as an integer subtype. |

### 6.2 Time semantics

Each simulated motor owns its own Alpha simulation clock. A global clock is
not introduced before shared-bus and multi-axis design work.

- startup resets state, simulation time, and revision to zero;
- reading a preview never advances time and never increments revision;
- a successful motor command changes velocity immediately, leaves simulation
  time unchanged, and increments revision once;
- a successful `advance_time(delta)` adds the finite non-negative delta to
  simulation time, applies the existing piecewise-constant integration, and
  increments revision once, including when `delta == 0.0`;
- a successful stop that applies zero velocity increments revision once;
- shutdown preserves position and simulation time, forces zero velocity, and
  increments revision once when it performs that state transition; and
- a rejected command, invalid time step, failed lifecycle operation, or preview
  read does not change simulation time or revision.

Equivalent accepted operation sequences must produce equal preview snapshots.
The preview contract contains no wall-clock timestamp.

The `delta == 0.0` rule is explicit because the existing simulation accepts
zero as a valid step. Treating the accepted operation as a revision preserves
an auditable deterministic operation sequence even when the numeric position
does not change.

### 6.3 Snapshot consistency

One preview request must return one coherent immutable view. The implementation
must serialize the capture with simulation mutations so it cannot combine
lifecycle from one operation with motor state from another.

For the initial one-motor Alpha, a snapshot is coherent only when all fields
describe the same completed mutation boundary. A later multi-resource slice
must define an atomic coordinator before it can claim a shared simulation
frame. Reading several motors sequentially and labeling the result atomic is
not acceptable.

Repeated reads of unchanged state must compare equal and serialize identically.
The returned value must not retain a live `Resource`, settings mapping, driver
object, exception, mutable collection, or callback.

## 7. Canonical serialized projection

The application boundary should serialize the domain snapshot as canonical
JSON with sorted keys, compact separators, UTF-8, one trailing newline, and no
NaN or infinity support. A one-motor example is:

```json
{"resources":[{"health_status":"healthy","health_summary":null,"identity":"sim_motor","kind":"motor","lifecycle_state":"running","state":{"angular_position_radians":1.5,"angular_velocity_radians_per_second":0.5,"revision":3,"simulation_time_seconds":2.0}}],"runtime_state":"running","schema_version":"1"}
```

This example defines shape, units, and ordering only. It is not evidence that a
CLI command or cross-process preview response exists.

Serialization must not contain:

- absolute or relative file paths;
- configuration contents or settings;
- environment variables or credentials;
- process IDs, user IDs, hostnames, or machine identity;
- socket, port, database, transport, or device identifiers;
- Python type names, memory addresses, exception text, or tracebacks;
- wall-clock timestamps;
- raw event or history database rows; or
- vendor-specific fields.

## 8. Read-only behavior

A preview observation must not:

- create, start, stop, restart, or shut down a runtime or resource;
- apply a motor command;
- advance simulation time;
- alter lifecycle, health, event, run-history, or revision state;
- open hardware or network transport;
- write to the RTO-3 history database;
- create a session when one is absent; or
- change cleanup ordering or ownership.

The preview is allowed to read already-owned in-memory state through typed
application methods. A cross-process adapter may use the existing private
session ownership boundary only after its protocol change is separately
specified and tested.

The provider must not depend on a read path whose failure accounting can mutate
health while observation is in progress. SIM-P1 therefore needs a
simulation-owned, side-effect-free state capture under the same serialization
boundary as command and time mutations; a renderer must not reach into private
resource fields.

## 9. Local access architecture

The product-facing contract has three layers:

```text
SimulatedMotor state
        ↓
typed SimulationPreviewProvider
        ↓
public application adapter (CLI first; Studio host later)
```

The typed provider is the source of truth. Renderers consume its serialized
projection; they do not recreate state by joining status, events, and SQLite
records.

### 9.1 Options considered

| Option | Strength | Problem | SIM-P0 disposition |
| --- | --- | --- | --- |
| Extend the existing private Unix-socket owner protocol with a read-only `preview` request | Reuses local ownership, permissions, bounded messages, session identity, and cleanup; no new listener. | Requires an explicit protocol/version change and regression matrix. The private wire format must not become the Studio API. | **Accepted transport direction for a later bounded slice**, behind a public adapter. |
| Reuse Motor gRPC directly | Existing typed motor read and loopback transport. | Same service includes write operations; lacks simulation time, revision, health, and complete preview consistency. | Not the Preview Alpha source of truth. |
| Add a loopback HTTP server | Browser-friendly. | Adds another server, security boundary, dependency, and lifecycle before the product model is proven. | Deferred. |
| Read RTO-3 SQLite from Studio | Durable records already exist. | History is not live component state; it couples UI to a private storage schema and cannot produce current motor values. | Prohibited. |
| In-process provider only | Smallest implementation and easiest deterministic testing. | Does not support the existing foreground owner from another process. | Required first layer, but insufficient as the final product adapter. |

### 9.2 Accepted sequencing

SIM-P1 should implement and test only the in-process typed provider and the
simulation clock/revision. SIM-P2 should add one bounded read-only
cross-process request plus a canonical public CLI JSON adapter. The private
wire shape may differ from the public JSON shape and must remain internal.

Studio Lite should call a local application host that consumes the public
adapter or the same typed provider. Browser code must not connect directly to
the Unix socket, import Python packages, or read the history database.

## 10. Error and limit rules

The preview implementation must fail closed with fixed HIYELX-owned errors.
Raw exception text must not cross the preview boundary.

Before SIM-P2 integration, its transport contract must freeze:

- exact command/request fields and types;
- protocol-version handling;
- maximum request and response bytes;
- maximum supported preview-resource count;
- invalid and missing session behavior;
- owner-not-ready and owner-stopping behavior;
- unsupported resource-kind behavior;
- operation deadline and exit code;
- malformed/duplicate-key/extra-field/oversized input handling; and
- disconnected-client behavior.

SIM-P0 does not invent exit codes before that transport design. Existing
session validation and ownership errors must remain stable unless a reviewed
contract explicitly changes them.

## 11. Acceptance matrix

| ID | Claim | Required evidence | Exit gate |
| --- | --- | --- | --- |
| SIMP0-CONTRACT-01 | Scope and evidence labels are explicit. | Read-only review against code, RTO docs, PRESEED, and this document. | No implemented claim for an accepted-but-unimplemented field or command. |
| SIMP1-SCHEMA-01 | Preview values are frozen, typed, finite, and versioned. | Unit tests for construction, invalid values, strict integer/version handling, and immutability. | Exact schema-v1 fields; no mutable or live object escapes. |
| SIMP1-TIME-01 | Simulation clock and revision obey Section 6.2. | Unit tests for startup, command, positive/zero time steps, stop, shutdown, and rejected operations. | Exact time/revision transitions. |
| SIMP1-DETERMINISM-01 | Equivalent operation sequences produce equal output. | Repeatable unit and integration sequences. | Equal snapshots and byte-equal canonical JSON. |
| SIMP1-READONLY-01 | Observation has no side effect. | Before/after snapshot, events, history, lifecycle, time, and revision assertions. | All observed state remains unchanged. |
| SIMP1-CONSISTENCY-01 | One snapshot describes one completed mutation boundary. | Controlled concurrency tests without sleeps as correctness signals. | No torn lifecycle/state/time/revision combination. |
| SIMP1-ORDER-01 | Resource order is deterministic. | Multi-resource in-process test even if product Alpha admits one motor. | Startup-plan order; identities unique. |
| SIMP1-SANITIZE-01 | Projection leaks no private/backend data. | Allowlist assertions and failure injection. | Only Section 6 fields; fixed summaries only. |
| SIMP2-LOCAL-01 | Cross-process preview remains local and bounded. | Real subprocess tests on private task-owned state roots. | No TCP/cloud; bounded timeout and message size; no session creation on read. |
| SIMP2-CLI-01 | Installed CLI emits canonical JSON. | Clean non-editable wheel verifier outside the checkout. | Exit `0`, exact one-line JSON plus newline, empty stderr. |
| SIMP2-NEGATIVE-01 | Invalid/missing/stopping/unsupported cases are sanitized. | Installed-wheel negative matrix. | Frozen codes and exact sanitized stderr; empty stdout. |
| SIMP2-CLEANUP-01 | Preview does not weaken owner cleanup. | Stop, SIGINT, forced-death, and client-disconnect regression coverage. | Existing RTO cleanup and history outcomes remain unchanged. |
| SIMP2-PORTABILITY-01 | Supported hosted platforms behave identically. | Ubuntu full gate and macOS Intel focused gate on the exact integration SHA. | Required preview tests and installed-wheel journey pass on both. |
| SIMP3-FOUNDER-01 | A person can interpret the preview without implementation knowledge. | Bounded founder black-box session using only public installed-wheel commands. | Correct explanation of position, velocity, time, lifecycle, health, and limitations. |

Physical hardware tests must remain skipped unless separately and explicitly
authorized. No row in this matrix can produce physical acceptance.

## 12. Work slices

### SIM-P0 — Preview Contract

Deliverables:

- current-capability and gap inventory;
- frozen domain schema and semantics;
- local access decision;
- acceptance matrix;
- explicit deferrals and evidence boundaries; and
- founder approval plus docs-only integration.

Exit: contract accepted and integrated; implementation still not started.

### SIM-P1 — In-process Preview Model

Deliverables:

- frozen preview dataclasses;
- per-simulated-motor time and revision;
- coherent read-only provider;
- canonical serializer;
- unit and in-process integration coverage; and
- no process protocol, CLI, or UI yet.

Exit: deterministic, sanitized preview snapshots are implemented and locally
accepted inside one process.

### SIM-P2 — Local Preview Adapter

Deliverables:

- reviewed private owner-protocol extension;
- one public read-only CLI command with canonical JSON;
- bounded negative and disconnect behavior;
- RTO cleanup/history regression coverage;
- clean installed-wheel verifier evidence; and
- Ubuntu plus macOS Intel hosted evidence.

Exit: a separate local process can inspect a running simulation without
mutating it or reading private files.

### SIM-P3 — Preview Acceptance and Handoff

Deliverables:

- founder black-box interpretation session;
- sanitized evidence record;
- synchronized README/PRESEED/architecture/evidence status; and
- a frozen handoff contract for Studio Lite.

Exit: Simulation/Preview Alpha is complete in its software scope and Studio
Lite may begin. Physical acceptance remains separate.

## 13. Studio Lite handoff

After SIM-P3, the first useful Studio screen should remain intentionally small:

- local session selector and connection state;
- runtime state and resource count;
- one motor card per ordered preview resource;
- lifecycle and health labels;
- position and velocity with explicit units;
- simulation time and revision;
- clear “simulation” labeling; and
- human-readable empty, unavailable, and sanitized error states.

The first Studio preview is observational. Start/stop, motor commands, time
controls, config editing, charts, replay, and camera are later product
decisions. A polished UI must not silently broaden the accepted runtime or
safety scope.

## 14. Risks and mitigations

| Risk | Consequence | Contract mitigation |
| --- | --- | --- |
| UI reads private socket or SQLite directly. | Product locks onto unstable internal formats. | Require typed provider and public adapter. |
| Preview read mutates or advances simulation. | Observation changes the experiment. | Side-effect-free gate and before/after assertions. |
| Wall clock enters simulation state. | Tests and UI become nondeterministic. | Explicit per-resource time only; no timestamps. |
| Lifecycle and motor state are captured at different boundaries. | Torn frames mislead the user. | Serialize preview capture with mutations. |
| gRPC write surface is treated as a read-only UI boundary. | UI unintentionally gains command capability. | Separate preview provider and adapter. |
| Multi-motor output is called an atomic frame too early. | False coordination claim. | Defer shared frame semantics until a coordinator exists. |
| Preview is mistaken for physics or hardware truth. | Product and safety expectations become misleading. | Permanent visible simulation and evidence labels. |
| Contract expands into Studio before the model stabilizes. | UI rework and hidden backend coupling. | Complete SIM-P1 and SIM-P2 before Studio implementation. |

## 15. Founder decisions approved

The founder approved the seven independent defaults on `2026-10-24`.

1. **Current-state boundary — Approved.** Preview Alpha is snapshot-only;
   replay and timeline work remain deferred.
2. **Per-resource clock — Approved.** `simulation_time_seconds` belongs to each
   simulated motor until shared-bus/multi-axis design introduces a coordinator.
3. **Revision semantics — Approved.** Revision increments once per successful
   state-mutating operation, including `advance_time(0.0)`, and does not
   increment on reads or rejected operations.
4. **Domain shape — Approved.** The schema-v1 field allowlist in Section 6
   excludes model names, settings, timestamps, paths, and vendor fields.
5. **Implementation order — Approved.** The in-process provider comes first,
   followed by a separately reviewed private owner-protocol extension and
   public CLI adapter.
6. **Studio boundary — Approved.** Studio Lite begins only after SIM-P3; its
   first preview screen is observational and has no controls.
7. **Evidence separation — Approved.** Physical, ARM64 hosted, release,
   publication, hard-real-time, and certified-safety claims remain outside
   SIM-P0 through SIM-P3.

Exact founder approval record:

```text
APPROVE SIM-P0 CONTRACT DEFAULTS
```

This approval freezes the SIM-P0 contract. It does not start SIM-P1, integrate
the document, publish a package, or create physical evidence.

## 16. Current status

```text
RTO-1 THROUGH RTO-4 COMPLETE: YES
SIM-P0 CONTRACT DRAFTED: YES
SIM-P0 FOUNDER APPROVAL: YES
SIM-P0 CONTRACT ACCEPTED: YES
SIM-P0 INTEGRATED: YES
SIM-P1 IMPLEMENTATION STARTED: NO
SIMULATION/PREVIEW ALPHA COMPLETE: NO
STUDIO LITE STARTED: NO
PHYSICAL HARDWARE ACCEPTANCE: NO
READY FOR BOUNDED SIM-P0 INTEGRATION: YES
```
