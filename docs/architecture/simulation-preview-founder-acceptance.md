# Simulation/Preview Alpha — Founder Preview Acceptance and Studio Lite Handoff

> - **Status:** Accepted / Frozen — SIM-P3 Founder Acceptance Contract
> - **Founder approval:** `APPROVE SIM-P3 CONTRACT DEFAULTS`
> - **Approval date:** `2026-10-26`
> - **Founder attestation amendment:** `APPROVE SIM-P3 FOUNDER ATTESTATION AMENDMENT`
> - **Amendment approval date:** `2026-10-28`
> - **Contract revision:** Accepted / Frozen, amended with Founder Interpretation Attestation Route
> - **Evidence baseline:** `0d64bbf6f6a814f3a2851757b5d965043c778233`
> - **Package version:** `0.2.0a1`
> - **Hosted baseline:** Quality gate `40182452809`
> - **Technical baseline:** SIM-P0, SIM-P1, and SIM-P2 accepted
> - **Accepted baseline revision:** `0d64bbf6f6a814f3a2851757b5d965043c778233`
> - **Accepted hosted baseline:** Quality gate `40182452809`
> - **SIM-P3 session preparation:** Historical attempts occurred; no session is currently prepared
> - **SIM-P3 session execution:** Historical live-session attempts occurred; none was accepted and no session is currently running
> - **Studio Lite implementation:** Not started
> - **Physical hardware acceptance:** Separate and pending
> - **Release, tag, and publication state:** Unchanged

This document is the founder-approved, accepted, and frozen SIM-P3 contract.
The founder approved all ten defaults on 2026-10-26 with the exact phrase
`APPROVE SIM-P3 CONTRACT DEFAULTS`, and approved the Founder Interpretation
Attestation amendment on 2026-10-28 with the exact phrase
`APPROVE SIM-P3 FOUNDER ATTESTATION AMENDMENT`. Normative words such as
**must** and **must not** define the bounded SIM-P3 acceptance routes and
handoff contract.

This contract builds on the accepted
[`SIM-P0 Preview Contract`](simulation-preview-alpha.md),
[`SIM-P2 Local Preview Adapter Contract`](simulation-preview-local-adapter.md),
[`RTO-4 Acceptance Contract`](runtime-operations-alpha-acceptance.md), and
[`clean installed-wheel evidence contract`](../development/clean-install-and-demo.md).
The prior
[`RTO-4 founder evidence record`](../evidence/2026-10-24-rto4-founder-acceptance.md)
is a format and authorization precedent, not SIM-P3 evidence. Repository-wide
evidence boundaries remain indexed in the
[`Software Evidence Index`](../evidence/software-evidence-index.md).

## A. Purpose and acceptance boundary

SIM-P3 is an acceptance-only phase. It is not feature development and must not
add or change runtime behavior, preview fields, CLI syntax, transport,
timeouts, tests, verifier behavior, workflow selection, package identity, or
Studio code.

SIM-P3 does not reproduce the SIM-P0/SIM-P1/SIM-P2 technical proof. It uses
the accepted SIM-P2 installed-wheel and hosted portability evidence as its
technical baseline, then answers five human questions:

1. Can the founder or a public user obtain a preview through the installed
   public command?
2. Can the founder interpret the output without implementation knowledge?
3. Can the founder distinguish deterministic simulation evidence from
   physical-hardware evidence?
4. Can the founder explain that preview is read-only and snapshot-only?
5. Can the session produce sufficient sanitized human evidence for a bounded
   Studio Lite handoff?

SIM-P3 supplies founder usability and interpretation evidence only. It does
not turn the founder into an external participant, extend hosted platform
coverage, or create physical, release, publication, safety, autonomy, or
production-readiness evidence.

Studio Lite must not start before the SIM-P3 contract is approved, a
contract-defined founder acceptance route passes, the founder records exact
`ACCEPT`, the sanitized evidence is reviewed and integrated, and the handoff
gate is explicitly closed.

### Accepted technical baseline

The contract uses this already accepted baseline without reopening it:

| Surface | Accepted evidence |
| --- | --- |
| Exact revision | `0d64bbf6f6a814f3a2851757b5d965043c778233` |
| Hosted run | Quality gate `40182452809` |
| Ubuntu | Job `121136175809`; `705 passed, 1 physical skipped`; exact 29-line installed-wheel result |
| macOS Intel | Job `121136175692`; GitHub-hosted `macos-15-intel` on Intel/x86_64; `365 passed`; exact 29-line installed-wheel result |
| SIM markers | All eight passed; final marker `sim-preview-acceptance=passed` |
| Package | `hiyelx==0.2.0a1` |

The exact session candidate must be selected and freshly preflighted when a
future session is separately authorized. This contract neither selects a future
session candidate nor prepares its environment.

## B. Evidence layers

Each claim has one primary evidence layer. Supporting links must not convert
one layer into another.

| Layer | Evidence | Current state | Boundary |
| --- | --- | --- | --- |
| E1 | SIM-P1 in-process technical evidence | Accepted | Typed schema, time/revision semantics, determinism, coherence, and read-only behavior inside one process. |
| E2 | SIM-P2 installed-wheel automated evidence | Accepted | One wheel, one non-editable environment, public CLI, negative matrix, cleanup, and exact 29-line verifier. |
| E3 | Ubuntu/macOS Intel hosted portability evidence | Accepted | Exact-SHA Ubuntu full gate and GitHub-hosted macOS Intel focused gate. It is not human usability evidence. |
| E4 | SIM-P3 founder interpretation evidence | Founder Interpretation Attestation candidate exists; awaiting bounded review and integration; accepted/integrated E4 evidence does not yet exist. | The candidate does not establish SIM-P3 completion. |
| E5 | Studio Lite UX evidence | Future | Evidence from a later implemented observational UI. SIM-P3 handoff is not Studio usability proof. |
| E6 | Physical hardware evidence | Separate and pending | Requires explicit physical authorization and its own evidence; simulation cannot substitute. |
| E7 | Release, tag, and publication evidence | Separate and pending | Requires a separate release decision; acceptance does not publish anything. |

No layer substitutes for another. In particular, E1–E4 cannot establish E5,
E6, or E7, and a later Studio screen cannot retroactively replace installed-
wheel or founder evidence.

## C. Stage model

### Stage 1 — Preparation

An operator or Codex may prepare the environment only after separate session
authorization. Preparation must provide:

- a clean detached checkout at the exact accepted session candidate SHA;
- exactly one freshly built HIYELX wheel;
- exactly one isolated, non-editable Python 3.12 virtual environment;
- `hiyelx` imports only from installed `site-packages`, outside the checkout;
- a task-owned copy of the canonical simulation configuration;
- task-owned local control state, history, home, temporary, and workspace
  roots;
- one installed foreground runtime owner; and
- no hardware enumeration, discovery, transport opening, torque, or movement.

The operator owns build, installation, source-isolation checks, readiness,
fallback shutdown, and cleanup. The founder usability timer does not run during
preparation. Preparation is not a session and creates no founder evidence.

### Stage 2 — Ready for Session

Before handoff, the operator must establish that the installed owner is ready
and that the public installed CLI is the only founder-facing surface. An
operator readiness or preview check must never be presented as a founder
result.

The founder receives only the public command sheet and a plain-language
statement that the session observes one local deterministic simulation. The
handoff must not reveal a real path, PID, run UUID, configuration content,
socket, database, virtual-environment location, username, hostname, or machine
identity.

The session starts only after the founder sends the exact message:

```text
BEGIN SIM-P3 SESSION
```

Any preparation status before that message remains non-session work.
The prepared command sheet, rubric summary, and usage explanation supplied
before that message are preparation material, not founder-journey assistance.
Any preparation explanation given before the exact begin message is outside
both the journey timer and its assistance metric.

### Stage 3 — Founder Journey

The timer starts when the exact begin message is received. The founder runs
only public commands from the installed wheel and answers the interpretation
rubric in their own words.

During the timed journey, the operator must not provide implementation
details, source paths, private Unix-socket instructions, SQLite instructions,
test names, field-by-field answers, or corrective interpretation. After the
exact begin message, every additional explanation, correction, hint,
rephrasing, command direction, or result interpretation is one assistance
instance. A founder request for clarification after that boundary is also an
assistance request. Assistance requests and instances, blockers, unexpected
leaks, and deviations are counted rather than silently repaired. A technical
safety stop or session termination is recorded as the applicable blocker or
failure and must not be disguised as assistance.

### Stage 4 — Decision and Cleanup

The founder gives exactly one decision:

```text
ACCEPT
```

or:

```text
REJECT
```

An evidence record may become a candidate only after exact `ACCEPT` and after
all session, interpretation, timing, cleanup, and repository-state gates pass.
The operator must stop the owner, reap all task-owned processes, remove all
task-owned control/history/workspace artifacts, and verify that the repository
remains unchanged.

A failure ends the attempt. A repeated bare `BEGIN SIM-P3 SESSION` is not retry
authorization. A new attempt may start only after the founder sends:

```text
RETRY SIM-P3 SESSION FROM STAGE 1
```

The retry must rebuild from Stage 1; it must not secretly reuse the failed
workspace, owner, wheel environment, or evidence state.

## D. Founder journey

The founder journey is exact `8/8`:

1. **Confirm environment and boundary.** Identify the supplied command as an
   installed-wheel CLI and state that the owner represents simulation, not
   physical hardware.
2. **Request a public preview.** Run `runtime preview` for the prepared session
   and observe one canonical JSON document with empty stderr.
3. **Interpret runtime scope.** Explain `runtime_state` and derive the resource
   count from the `resources` array.
4. **Interpret the resource.** Explain identity, kind, lifecycle state, health
   status, and the distinction between runtime and resource lifecycle.
5. **Interpret motor values.** Explain angular position in radians and angular
   velocity in radians per second.
6. **Interpret simulation metadata.** Explain `simulation_time_seconds` and
   `revision`, including why neither is a wall-clock timestamp.
7. **Observe repeatability and read-only behavior.** Run the same preview a
   second time against unchanged state, observe byte-equal output, and explain
   that observation did not advance or mutate the simulation.
8. **Observe a sanitized negative and explain limits.** Preview a missing or
   stopped session, identify the fixed sanitized failure, and explain that the
   successful output is a simulation snapshot—not physics fidelity, physical
   hardware, autonomy, hard-real-time, or certified-safety evidence.

The journey must not use or mention a private Unix socket command, SQLite
query, source-tree invocation, editable import, raw configuration read, or
private process inspection.

## E. Interpretation rubric

The rubric topics below apply to both acceptance routes. Their evidence and
timing requirements are route-specific:

- **Original live-session route:** every row must pass in the founder's own
  words during the timed journey, without answer coaching. The existing live
  timer and zero-assistance gates remain unchanged.
- **Founder Interpretation Attestation Route:** every topic must pass in a
  founder-authored written attestation. This does not claim a timed journey or
  a zero-assistance live-session pass and does not require a new runtime
  session. The attestation must cover every rubric meaning and evidence
  boundary below.

| Topic | Required interpretation | Failure example |
| --- | --- | --- |
| `runtime_state="running"` | The local Runtime Manager completed startup and was running at this snapshot boundary. It does not guarantee future uptime or physical operation. | “The robot is physically running.” |
| Resource count | The number of entries in `resources`; Preview Alpha currently admits exactly one supported resource. | Treating a missing field or hidden config as the count. |
| Resource identity and kind | `identity` is the stable application-level resource identity, and `kind` is the general resource category—`motor` for the current preview. Neither field is a vendor or model name, device path, physical-device discovery result, physical-hardware acceptance evidence, or model-specific/backend-private detail. | Inferring a vendor, model, device path, discovered physical device, or hardware acceptance from either field. |
| `lifecycle_state="running"` | This resource completed its lifecycle start. It is distinct from the manager-level runtime state. | Treating runtime and resource lifecycle as the same field. |
| `health_status="healthy"` | No known resource fault is represented at observation time. It does not prove physics fidelity, hardware health, safety, or certification. | “Healthy proves the physical motor is safe.” |
| Position | `angular_position_radians` is angular position in radians. | Degrees, turns, or an unspecified unit. |
| Velocity | `angular_velocity_radians_per_second` is angular velocity in radians per second. | RPM or radians without the per-second dimension. |
| Simulation time | `simulation_time_seconds` is explicit per-resource simulated time, not wall-clock elapsed time or a timestamp. | Treating it as local time or process uptime. |
| Revision | A non-negative counter that changes once after a successful state-mutating operation; preview reads do not increment it. | Treating it as a wall-clock sequence or read counter. |
| Read-only snapshot | Preview observes one current snapshot and does not start, stop, command, advance, or otherwise mutate state. | Claiming preview advances the simulation. |
| Simulation boundary | Output describes deterministic simulation state; it is not physics-fidelity or physical-hardware evidence. | Claiming a real actuator was validated. |
| Local-first boundary | Preview requires no cloud or control plane; it uses the local public application boundary. | Claiming cloud connectivity is required. |
| Claim boundary | Output is not autonomy, hard-real-time, production-readiness, or certified-safety evidence. | Making any of those claims. |

Any incorrect scope answer is a session failure even if every command exits
successfully.

## F. Public command transcript

### Founder-owned commands

The founder command sheet contains only these sanitized public forms:

```bash
hiyelx runtime status --session sim-p3-founder
hiyelx runtime preview --session sim-p3-founder
hiyelx runtime preview --session sim-p3-founder
hiyelx runtime preview --session missing
```

The first two successful preview outputs must be canonical one-line JSON with
one trailing newline and empty stderr. The missing-session command must exit
`5`, emit no stdout, and emit only:

```text
error: runtime session is not running
```

### Operator-owned preparation and cleanup

Start and stop belong to the operator, outside the founder timer:

```bash
hiyelx runtime start <CANONICAL_SIMULATION_CONFIG> --session sim-p3-founder
hiyelx runtime stop --session sim-p3-founder
```

`<CANONICAL_SIMULATION_CONFIG>` is a sanitized placeholder, not a publishable
path. Build, venv, environment, readiness, process-reaping, and filesystem
cleanup commands are operator-owned and must not be copied into the founder
journey or published evidence.

## G. Duration and usability defaults

These values are accepted defaults and binding thresholds for any future,
separately authorized session:

| Measurement | Accepted pass threshold |
| --- | ---: |
| Founder journey hard limit | At most `10 minutes` |
| Founder journey target | At most `5 minutes` |
| Journey completion | Exact `8/8` |
| Assistance requests or instances after exact `BEGIN SIM-P3 SESSION` | `0` |
| Blockers | `0` |
| Unexpected traceback/path/config/credential leak | `0` |
| Runtime/process leftovers | `0` |
| Task-owned artifact leftovers | `0` |

Preparation time is recorded separately if useful but must not be included in
the founder usability duration.

## H. Failure and retry semantics

Any of the following fails the current attempt:

- owner not ready at handoff;
- an unexpected nonzero public-command exit;
- successful preview output that is noncanonical JSON or has unexpected
  stderr;
- inability to interpret any required field or unit;
- confusion between simulation and physical evidence;
- confusion about snapshot-only or read-only behavior;
- a traceback or private path, PID, config, credential, token, socket,
  database, username, hostname, or machine-identity leak;
- founder journey duration greater than 10 minutes;
- any assistance request or instance after exact `BEGIN SIM-P3 SESSION`;
- cleanup failure, live task-owned process, or task-owned artifact leftover;
  or
- repository SHA, index, or dirty-state drift.

After failure, the operator must not:

- create an evidence candidate;
- report founder acceptance;
- silently reuse the workspace or owner;
- automatically retry; or
- infer retry authority from a repeated begin message.

The attempt remains failed until the founder separately authorizes the exact
retry phrase in Section C. A retry is a new session with new measurements and
must disclose that a prior attempt occurred.

## I. Evidence record

The evidence path for a future accepted session is:

```text
docs/evidence/YYYY-MM-DD-sim-p3-founder-acceptance.md
```

Contract approval alone does not authorize evidence creation. Evidence may be
created only after one of the two routes below passes, the founder gives exact
`ACCEPT`, cleanup succeeds, and the repository remains unchanged.

### Original live-session route

The original route remains a timed, zero-assistance `8/8` live journey under
Sections C–H. Its assistance, timing, interpretation, cleanup, and repository
gates remain binding. Failed attempts under this route are not acceptance
evidence and cannot be retroactively converted into zero-assistance passes.
This route does not change the record or metrics of any prior attempt.

### Founder Interpretation Attestation Route

This separate route was approved by the exact founder amendment phrase
`APPROVE SIM-P3 FOUNDER ATTESTATION AMENDMENT`. It permits E4 Founder
Interpretation Attestation evidence without a new timed runtime session. It
does not retroactively pass an original live-session attempt, assert an
assistance count of zero for such an attempt, or reclassify any failed attempt.
Each evidence candidate must state which route it uses; claims cannot be
combined across routes.

All of these gates must pass:

1. SIM-P0, SIM-P1, and SIM-P2 technical acceptance exists.
2. Exact candidate and package identity are verified.
3. The founder has observed public installed-wheel status/preview results.
4. The founder completes every interpretation rubric topic in their own
   written words.
5. The founder correctly explains simulation/physical and product-claim
   boundaries.
6. The founder gives exact `ACCEPT`.
7. The founder gives exact amendment approval
   `APPROVE SIM-P3 FOUNDER ATTESTATION AMENDMENT`.
8. Relevant session/workspace cleanup succeeded.
9. Repository state remained unchanged.
10. No hardware operation occurred.
11. The record is sanitized under this section.
12. Until the evidence is boundedly reviewed and integrated, SIM-P3 is not
    complete.

This route does not require a new timed runtime session, a zero-assistance
session metric, a chat-controller token protocol, repeated wheel builds, or
repeated public command execution.

### Common record requirements

A record under either route must include:

- exact candidate SHA;
- wheel filename and package version;
- platform and architecture;
- accepted hosted baseline run and Ubuntu/macOS job IDs;
- exact route and `Founder product decision: ACCEPT`;
- complete results for every interpretation-rubric row;
- founder explanation of simulation, read-only, local-first, physical,
  release, autonomy, hard-real-time, and safety boundaries;
- cleanup, repository, and hardware-operation status where applicable;
- explicit separation of automated, founder, Studio, physical, and
  release/publication evidence;
- sanitization status; and
- bounded review/integration state.

### Original live-session record requirements

An original live-session record must additionally include:

- elapsed duration, excluding preparation;
- exact journey completion `8/8`;
- assistance, blocker, leak, live-process, and artifact-leftover counts;
- sanitized exact timed public command transcript;
- whether the session was retried and the number of live-session attempts; and
- exact session decision chronology.

These live-session measurements must not be inferred from or attributed to an
attestation record.

### Founder Interpretation Attestation record requirements

An attestation record must additionally include:

- exact `Founder amendment approval: APPROVE SIM-P3 FOUNDER ATTESTATION AMENDMENT`;
- the founder-authored written interpretation;
- retained public command forms and results as supporting context, clearly
  distinguished from any new execution;
- transparency that no new runtime execution occurred for the attestation;
- transparency that original failed live attempts were not reclassified; and
- relevant retained cleanup evidence.

Elapsed time, `8/8`, assistance, retry, and other session-only metrics are
**not applicable to the attestation route**. They must be omitted or marked
not applicable; if included for historical context, they must be explicitly
identified as non-candidate attempt data and never as attestation acceptance
measurements.

An attestation candidate must not invent elapsed/`8/8`/assistance/retry
metrics, claim a new command execution, or use original failed-attempt metrics
as acceptance measurements. The attestation route does not require repeated
public command execution; retained command forms/results may support the
founder's interpretation without claiming a rerun.

Exact `REJECT` or any session failure must never be classified as an
acceptance evidence candidate, accepted session record, SIM-P3 founder
acceptance, or SIM-P3 completion. If retained for failure/retry audit, its
record is a separate **non-candidate attempt record**. Such a record:

- is not acceptance evidence and produces no founder acceptance;
- cannot be added to the evidence index as accepted evidence;
- cannot establish SIM-P3 completion;
- may serve only as a failure/retry audit trail; and
- must carry exact status `Rejected Attempt — Not Acceptance Evidence` for
  exact `REJECT`, or `Failed Attempt — Not Acceptance Evidence` for another
  session failure.

The record must not include:

- a real temporary, checkout, home, venv, socket, or database path;
- PID, UID, real run UUID, username, hostname, or machine identity;
- runtime-history timestamps or raw database rows;
- raw configuration or environment values;
- credential, token, secret, or authorization material;
- private protocol payloads; or
- unsanitized exception text or traceback.

## J. Studio Lite handoff

If SIM-P3 is later accepted, the frozen minimum Studio Lite capability handed
to a separate STUDIO-P0 contract is observational only:

- local session selector;
- connection state;
- runtime state;
- resource count;
- one ordered motor card;
- resource identity and kind;
- lifecycle and health;
- angular position in radians;
- angular velocity in radians per second;
- simulation time;
- revision;
- a persistent and prominent `SIMULATION` label;
- empty state;
- unavailable state; and
- sanitized error state.

The first Studio Lite scope explicitly defers:

- start/stop controls;
- motor commands;
- simulation-time controls;
- configuration editing;
- charts, replay, or timeline;
- camera or vision;
- shared bus or multi-axis coordination;
- 3DOF; and
- autonomy.

Studio must not connect directly to the private Unix socket, query SQLite,
read runtime files, import backend-private types, or reconstruct preview state
from history. It must consume a public application boundary. The exact local
host and IPC form—such as an application host interface—remains a future
STUDIO-P0 contract decision and is not chosen by SIM-P3.

SIM-P3 acceptance would authorize only bounded STUDIO-P0 contract work. It
would not authorize Studio implementation by itself.

## K. Acceptance matrix

| ID | Claim | Required evidence | Exit gate |
| --- | --- | --- | --- |
| `SIMP3-PREP-01` | Preparation is isolated from the founder timer and uses the exact candidate. | Operator preparation record with sanitized SHA, wheel, Python, isolation, owner-readiness, and cleanup ownership. | Clean detached checkout; one wheel; one non-editable venv; installed import only; no timer started. |
| `SIMP3-INSTALL-01` | The founder uses only the installed public CLI. | Sanitized transcript plus import/source-isolation preparation result. | No source-tree, editable, socket, SQLite, or private command in the founder journey. |
| `SIMP3-JOURNEY-01` | The founder completes the exact public journey. | Timed session record. | Exact `8/8`, at most 10 minutes, zero assistance after exact `BEGIN SIM-P3 SESSION`, zero blocker, and explicit decision. |
| `SIMP3-INTERPRET-01` | The founder correctly interprets all fields, units, and evidence limits. | Completed Section E rubric in the founder's own words. | Every rubric row passes without answer coaching. |
| `SIMP3-READONLY-01` | The founder observes that repeat preview does not mutate state. | Two byte-equal unchanged preview outputs plus founder explanation. | Time, revision, lifecycle, health, and values remain unchanged by observation. |
| `SIMP3-NEGATIVE-01` | A missing or stopped session fails predictably. | Public negative command transcript. | Exit `5`, empty stdout, exact fixed stderr, no session creation. |
| `SIMP3-SANITIZE-01` | Session and evidence leak no private data. | Transcript/evidence allowlist scan and zero leak count. | No forbidden path, identity, config, credential, protocol, or traceback content. |
| `SIMP3-CLEANUP-01` | The attempt leaves no task-owned process or artifact. | Operator cleanup record and final repository-state check. | Owner stopped; process/artifact counts zero; repository unchanged. |
| `SIMP3-EVIDENCE-01` | Founder evidence is complete and remains distinct from other layers. | Sanitized evidence candidate satisfying Section I for its declared route. | Exact `Founder product decision: ACCEPT`; route-specific required fields are present; non-candidate attempts remain excluded; automated, Studio, physical, and release claims remain separate. |
| `SIMP3-HANDOFF-01` | Studio Lite receives only the frozen observational minimum. | Reviewed handoff checklist against Section J. | All required fields/states included; all controls and private-boundary access excluded. |
| `SIMP3-ATTEST-01` | Founder-authored attestation is a separate E4 route and does not alter historical live-session results. | Founder’s own written rubric, exact product `ACCEPT`, exact amendment approval, sanitized candidate, and bounded review/integration record. | Every attestation gate in Section I passes; no failed live attempt is reclassified; SIM-P3 remains incomplete until review and integration. |

Route assignment is explicit:

- **Original live-session route gates:** `SIMP3-PREP-01`,
  `SIMP3-INSTALL-01`, `SIMP3-JOURNEY-01`, `SIMP3-INTERPRET-01`,
  `SIMP3-READONLY-01`, `SIMP3-NEGATIVE-01`, `SIMP3-SANITIZE-01`,
  `SIMP3-CLEANUP-01`, `SIMP3-EVIDENCE-01`, and `SIMP3-HANDOFF-01`.
- **Founder Interpretation Attestation Route gates:** `SIMP3-INTERPRET-01`,
  `SIMP3-SANITIZE-01`, `SIMP3-EVIDENCE-01`, `SIMP3-HANDOFF-01`, and
  `SIMP3-ATTEST-01`.

For the attestation route, PREP, INSTALL, READONLY, NEGATIVE, and CLEANUP
records may be supporting retained public or technical inputs; they are not
live-session exit gates to be rerun. `SIMP3-JOURNEY-01` does not apply to the
attestation route. That route makes no timed or zero-assistance live-journey
claim. Shared gates must use their route-specific evidence forms. Neither
route produces physical, release, publication, safety, or Studio UX evidence.

## L. Founder decision points

The following ten independent defaults were approved by the founder on
2026-10-26. Their content and order are frozen by this contract.

1. **SIM-P3 acceptance-only scope.** SIM-P3 adds no technical feature and
   produces only founder interpretation and handoff evidence.

   Approval state: Approved by founder on 2026-10-26.
2. **Installed-wheel/public-command-only journey.** The founder uses only the
   installed `hiyelx` public CLI; source and private interfaces are excluded.

   Approval state: Approved by founder on 2026-10-26.
3. **Preparation/timer separation.** Operator preparation and cleanup remain
   outside the founder usability timer.

   Approval state: Approved by founder on 2026-10-26.
4. **Exact `8/8` journey.** All eight Section D steps are mandatory and no
   partial completion receives acceptance credit.

   Approval state: Approved by founder on 2026-10-26.
5. **Duration defaults.** Use a 10-minute hard limit and a 5-minute target for
   the founder journey only.

   Approval state: Approved by founder on 2026-10-26.
6. **Zero-assistance default.** Prepared material and explanations before the
   exact begin message are outside the metric. Any assistance request or
   instance after exact `BEGIN SIM-P3 SESSION`, or any blocker, fails the
   attempt.

   Approval state: Approved by founder on 2026-10-26.
7. **Failure/retry authorization.** Failure ends the attempt; only exact
   `RETRY SIM-P3 SESSION FROM STAGE 1` authorizes a new attempt.

   Approval state: Approved by founder on 2026-10-26.
8. **Sanitized evidence requirement.** Evidence must follow the Section I
   allowlist and denylist and exist only after explicit `ACCEPT` plus cleanup.

   Approval state: Approved by founder on 2026-10-26.
9. **Observational Studio handoff.** SIM-P3 may hand only the Section J
   read-only minimum to a later STUDIO-P0 contract.

   Approval state: Approved by founder on 2026-10-26.
10. **Physical/release/publication separation.** Keep physical acceptance,
    tag, release, registry publication, and version changes outside SIM-P3.

    Approval state: Approved by founder on 2026-10-26.

The exact founder approval record is:

```text
APPROVE SIM-P3 CONTRACT DEFAULTS
```

The founder supplied that exact approval on 2026-10-26. It is not
`BEGIN SIM-P3 SESSION` or `RETRY SIM-P3 SESSION FROM STAGE 1`; it does not
authorize session preparation, session execution, an acceptance result,
evidence creation, commit, push, or Studio implementation.

## M. Current contract status

```text
SIM-P2 ACCEPTED: YES
SIM-P3 FOUNDER CONTRACT APPROVAL: YES
SIM-P3 CONTRACT ACCEPTED: YES
SIM-P3 CONTRACT INTEGRATED: NO
SIM-P3 SESSION PREPARED: NO
SIM-P3 SESSION STARTED: NO
SIM-P3 FOUNDER ACCEPTANCE: NO
SIM-P3 COMPLETE: NO
STUDIO LITE STARTED: NO
PHYSICAL HARDWARE ACCEPTANCE: NO
RELEASE/TAG/PUBLICATION STATE CHANGED: NO
```

Founder approval of this contract is not session preparation or execution and
does not authorize repository integration. No owner, wheel environment,
evidence record, Studio implementation, physical operation, release, tag,
publication, version change, commit, or push is authorized here.
