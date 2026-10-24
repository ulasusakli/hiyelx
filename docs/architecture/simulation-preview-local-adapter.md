# Simulation/Preview Alpha — SIM-P2 Local Preview Adapter Contract

> - **Status:** Accepted / Frozen — SIM-P2 contract
> - **Founder approval:** `APPROVE SIM-P2 CONTRACT DEFAULTS`
> - **Approval date:** `2026-10-24`
> - **Evidence baseline:** `8c53c56f58649d6bccae9e2a5f4109ee69bb27b6`
> - **Package version:** `0.2.0a1`
> - **Prerequisites:** RTO-1 through RTO-4 accepted; SIM-P0 accepted; SIM-P1 integrated
> - **Implementation status:** Not started
> - **Contract integration:** This bounded docs-only commit
> - **Physical hardware acceptance:** Separate and pending

Normative words such as **must** and **must not** define the founder-approved
contract. They do not claim that the adapter, command, tests, or installed
wheel evidence exist. Founder approval is recorded here; repository
integration remains a separate bounded docs-only step.

## 1. Purpose

SIM-P2 turns the accepted in-process preview model into one bounded local
application adapter:

```text
running local simulation owner
        ↓ private Unix-socket preview request
typed SimulationPreviewSnapshot
        ↓ public CLI adapter
canonical one-line JSON
```

The outcome is deliberately narrow: a separate local process can inspect one
running deterministic simulated motor without mutating the runtime, creating a
session, reading SQLite, importing drivers, or gaining command capability.

This contract refines the accepted
[`SIM-P0 Preview Contract`](simulation-preview-alpha.md). If the documents
conflict, SIM-P0 continues to govern the domain snapshot and this document
governs only the SIM-P2 transport, CLI, limits, and acceptance evidence.

## 2. Current baseline

At the evidence baseline the repository provides:

- a foreground local owner with private Unix-domain socket control;
- strict, canonical, bounded protocol-v1 `status` and `stop` messages;
- exact integer version validation and duplicate-key rejection;
- a three-second local control timeout with no retry;
- private `0700` state/session directories and `0600` artifacts;
- deterministic session ownership and cleanup;
- frozen in-process preview values and canonical JSON serialization;
- per-simulated-motor time and revision;
- a side-effect-free `SimulationPreviewProvider`; and
- no public or private cross-process preview command.

The protocol implementation is private. The CLI is the public application
boundary. Future Studio code must not connect to the socket or reproduce its
wire schema.

## 3. Scope

SIM-P2 includes:

- one additive private `preview` request;
- one strict private preview reply;
- typed encode/decode validation at both ends;
- one public JSON-only CLI command;
- exact local limits, timeouts, failures, and exit codes;
- real subprocess, disconnect, cleanup, and negative coverage;
- clean non-editable wheel evidence; and
- Ubuntu plus macOS Intel hosted evidence on the integration SHA.

SIM-P2 does not include:

- runtime start, stop, motor command, or time-advance controls in the preview
  operation;
- polling, watch mode, streaming, subscriptions, background sampling, or
  automatic refresh;
- multiple-resource atomic-frame claims;
- a new socket, daemon, HTTP server, TCP port, public protobuf, or database;
- direct browser or Studio access to the private socket;
- replay, recording, camera, 2D/3D geometry, physics, collision, or timeline;
- remote access, cloud/control-plane dependency, authentication, telemetry,
  retry, reconnect, or recovery;
- hardware, serial, discovery, transport, torque, or movement;
- hard-real-time, production-readiness, or certified-safety claims; or
- package-version change, tag, release, registry publication, or compatibility
  guarantee.

## 4. Public CLI contract

The only new public command is:

```bash
hiyelx runtime preview --session <SESSION>
```

There is no text mode and no `--json` switch. Successful stdout is the exact
canonical JSON projection already frozen by SIM-P0:

- sorted object keys;
- compact separators;
- UTF-8;
- finite JSON numbers only;
- exactly one JSON document;
- exactly one trailing newline; and
- no other stdout or stderr content.

The private session envelope is removed before rendering. Public JSON does not
contain the session identifier, protocol version, socket path, PID, config,
history data, or private error fields.

The CLI performs one request and exits. It does not create a missing session,
start an owner, wait for readiness, retry, poll, or cache a snapshot.

## 5. Private request contract

The request uses the existing canonical JSON-line envelope:

```json
{"command":"preview","protocol_version":1,"session":"alpha"}
```

The exact top-level key set is:

```text
command, protocol_version, session
```

Rules:

- `command` must be the exact string `"preview"`;
- `protocol_version` must be the exact integer `1`; booleans, floats, strings,
  null, and other integers are invalid;
- `session` must pass the existing session-ID validator;
- the document must be a UTF-8 JSON object terminated by one newline;
- duplicate keys, missing keys, extra keys, wrong primitive types, malformed
  UTF-8/JSON, multiple documents, and oversized input fail closed; and
- the request must not contain resource identity, run ID, config, cursor,
  method name, mutation, or renderer options.

### 5.1 Protocol-version decision

SIM-P2 keeps private protocol version `1`. The preview command is an additive
capability: existing status/stop request and response shapes do not change, and
existing v1 clients remain valid. An older owner may return the existing
sanitized `unknown_command` failure to a newer preview client; that becomes a
public control-protocol failure.

Any incompatible envelope or existing-message change requires a later version
bump. Version `1` is not a public compatibility guarantee.

## 6. Private success reply

The exact private reply is a canonical JSON line with this structure:

```json
{"kind":"preview","ok":true,"protocol_version":1,"result":{"preview":{"resources":[{"health_status":"healthy","health_summary":null,"identity":"sim_motor","kind":"motor","lifecycle_state":"running","state":{"angular_position_radians":1.5,"angular_velocity_radians_per_second":0.5,"revision":3,"simulation_time_seconds":2.0}}],"runtime_state":"running","schema_version":"1"},"session":"alpha"}}
```

The top-level and result key sets are exact:

```text
top level: kind, ok, protocol_version, result
result:    preview, session
```

The nested preview object has exactly the accepted SIM-P0 schema. The server
constructs it from a typed `SimulationPreviewSnapshot`; the client decodes it
back into validated frozen preview values. No live resource, driver, mapping,
callback, exception, or raw dictionary crosses the public boundary.

The client renders the validated nested snapshot with the SIM-P1 canonical
serializer. It must not print the private reply directly.

## 7. Resource bound and coherence

The cross-process Preview Alpha supports exactly one preview resource:

```text
MIN_PREVIEW_RESOURCES = 1
MAX_PREVIEW_RESOURCES = 1
```

Zero resources and more than one resource are unsupported for the public
preview operation. Existing runtime start, status, stop, history, and cleanup
behavior remains available for configurations otherwise allowed by RTO.

This bound prevents a sequentially captured multi-resource tuple from being
misrepresented as one atomic shared frame. The in-process provider retains its
deterministic ordered tuple because ordering is part of the accepted schema;
shared-frame work remains deferred to the future shared-bus/multi-axis phase.

One successful response must describe one completed mutation boundary. A
transitional runtime or detected overlapping mutation returns no snapshot and
fails closed without retry.

## 8. Size, timeout, and connection rules

SIM-P2 reuses the existing control-message limit:

```text
MAX_MESSAGE_BYTES = 8192
```

The limit includes the trailing newline and applies independently to request
and reply. A response that cannot be encoded within the limit fails closed;
partial JSON must never be written as success.

The preview client has one monotonic total I/O deadline:

```text
PREVIEW_REQUEST_TIMEOUT_SECONDS = 3.0
```

The deadline covers Unix-socket connect, request drain, response read, and
reply decoding. There is no retry, reconnect, fallback file read, PID signal,
or secondary transport. The child/socket operation must be reaped or closed on
every exit path.

The server continues to enforce one request per connection. A client that
disconnects before or during the reply causes no owner failure, runtime
mutation, history mutation, retry, or leaked handler. Connection errors remain
sanitized and the owner continues serving later clients.

## 9. Session and lifecycle behavior

| Condition | Required outcome |
| --- | --- |
| Invalid session ID | Reject before path construction; no artifacts. |
| Missing or unpublished session | Existing `SessionNotRunningError`; no session creation. |
| Ready, running, one supported motor | Return one validated preview snapshot. |
| Runtime `STARTING` or `STOPPING` after a request was accepted | Private `preview_unavailable`; no snapshot and no retry. |
| Mutation overlaps capture | Private `preview_unavailable`; no snapshot and no retry. |
| Zero or multiple resources | Private `preview_unsupported`; no partial snapshot. |
| Unsupported resource implementation/kind | Private `preview_unsupported`; no guessed projection. |
| Server has stopped accepting connections | Preserve existing missing-session/control-failure classification; never return stale preview data. |
| Client disconnect | Owner remains running; handler closes; no mutation or retry. |

Preview must not change readiness publication, signal installation, stop
coordination, safe-stop, shutdown, history finalization, or artifact-cleanup
ordering.

## 10. Private failures and public exit codes

Two fixed private failure codes are added:

| Private code | Exact private message |
| --- | --- |
| `preview_unavailable` | `runtime preview is unavailable` |
| `preview_unsupported` | `runtime preview is unsupported` |

No backend-authored text, exception text, identity, path, config, PID, or raw
state may be included. Unexpected provider/encoder failures use the existing
`internal_failure` reply and do not expose the exception.

The public CLI map is:

| Condition | Exit | Exact stderr | stdout |
| --- | ---: | --- | --- |
| Success | `0` | empty | canonical preview JSON |
| Invalid session ID | `3` | `error: runtime session ID is invalid` | empty |
| Session not running | `5` | `error: runtime session is not running` | empty |
| Protocol, malformed reply, deadline, incompatible owner, or local I/O failure | `6` | `error: runtime control failed` | empty |
| Unsupported platform | `9` | `error: runtime control is unsupported on this platform` | empty |
| Preview temporarily unavailable or incoherent | `12` | `error: runtime preview is unavailable` | empty |
| Preview resource shape/count unsupported | `13` | `error: runtime preview is unsupported` | empty |

Existing exit codes `0` and `2` through `11` retain their meanings. New codes
`12` and `13` are preview-only. Parser misuse remains argparse behavior and is
not remapped by this contract.

## 11. Sanitization and read-only invariants

Private and public preview output is an allowlist projection. It must not
contain:

- absolute or relative paths;
- configuration contents, settings, environment variables, or credentials;
- PID, UID, hostname, machine identity, socket, port, database, or device;
- model/vendor names, Python types, repr strings, memory addresses, exception
  text, or tracebacks;
- wall-clock timestamps, raw events, run IDs, or history rows; or
- fields outside the frozen schema.

One preview request must leave unchanged:

- runtime and resource lifecycle;
- motor position, velocity, simulation time, and revision;
- health and event recorder state;
- run history and history database bytes;
- session manifest, lock, and socket ownership; and
- stop/shutdown/cleanup coordination.

The server must obtain the snapshot through the typed provider. Neither server
nor CLI may read private motor fields, SQLite, manifest contents, or config to
reconstruct a preview.

## 12. Installed-wheel acceptance

SIM-P2 extends the existing `scripts/verify_clean_install.py` journey. It must
reuse the same clean non-editable wheel and isolated virtual environment; a
second verifier or editable/source-tree import is not allowed without a
separate reviewed reason.

The existing 21-line RTO output remains an exact prefix. Eight new unique
markers follow in this order:

```ini
sim-preview-wheel=passed
sim-preview-source-isolation=passed
sim-preview-active=passed
sim-preview-repeat=passed
sim-preview-negative=passed
sim-preview-disconnect=passed
sim-preview-cleanup=passed
sim-preview-acceptance=passed
```

Success output is therefore exactly 29 lines. The aggregate marker is emitted
last and only after all earlier preview gates pass. Partial or failed journeys
emit none of the eight success markers.

The installed journey must prove:

1. the command is provided only by the installed wheel;
2. an active owner returns exact canonical JSON with empty stderr;
3. repeated unchanged reads are byte-for-byte equal;
4. active time/revision/events remain unchanged by observation;
5. invalid, missing, unavailable, unsupported, malformed, oversized, and
   incompatible replies fail with exact sanitized output;
6. a disconnected client does not stop or damage the owner;
7. normal stop still finalizes `completed/cli_stop` with events `0..11`; and
8. control and task-owned artifacts are removed by the existing cleanup path.

## 13. Hosted portability

The integration SHA must pass:

- Ubuntu full Ruff, strict Pyright, full pytest, and clean installed-wheel
  verifier; and
- GitHub-hosted `macos-15-intel` focused tests plus the same clean installed-
  wheel verifier.

The macOS focused selection must include the SIM-P1/SIM-P2 simulation preview
unit tests, control tests, CLI tests, runtime subprocess tests, and verifier
tests. A green macOS job that does not select the preview tests is not SIM-P2
portability evidence.

Runner-capacity cancellation with no assigned runner and no steps is an
environment block, not a product pass. An assigned runner test failure is a
failed acceptance gate. ARM64 founder/local execution does not replace the
required hosted Intel evidence.

## 14. Acceptance matrix

| ID | Claim | Required evidence | Exit gate |
| --- | --- | --- | --- |
| SIMP2-PROTOCOL-01 | Preview request/reply is strict, bounded, and versioned. | Unit encode/decode and malformed matrix. | Exact keys/types; v1 exact integer; 8192-byte limit. |
| SIMP2-LOCAL-01 | Preview remains local and one-shot. | Real Unix-socket subprocess tests. | No TCP/cloud, retry, polling, or session creation. |
| SIMP2-CLI-01 | Installed CLI emits canonical public JSON. | Clean non-editable wheel journey. | Exit `0`, exact JSON plus newline, empty stderr. |
| SIMP2-READONLY-01 | Observation changes no runtime state. | Before/after state, event, history, and artifact assertions. | All observed state and bytes unchanged. |
| SIMP2-NEGATIVE-01 | Invalid and unavailable cases are sanitized. | Unit and installed-wheel negative matrix. | Exact exits/stderr; empty stdout; no raw details. |
| SIMP2-DISCONNECT-01 | Client loss cannot damage the owner. | Real socket disconnect test. | Owner remains responsive; no leaked handler or mutation. |
| SIMP2-CLEANUP-01 | Preview does not weaken RTO cleanup. | Stop, SIGINT, crash, concurrent stop, and cleanup regression. | Existing durable outcomes and cleanup order unchanged. |
| SIMP2-PACKAGE-01 | Preview works outside the checkout. | Single-wheel verifier with source isolation. | No editable/source-tree import. |
| SIMP2-PORTABILITY-01 | Required platforms execute preview behavior. | Exact-SHA Ubuntu and macOS Intel jobs. | Preview tests and 29-line verifier pass on both. |

No acceptance row provides physical hardware, release, publication,
hard-real-time, or certified-safety evidence.

## 15. Implementation slices after approval

### SIM-P2A — Private preview transport

- add typed preview request/reply values;
- extend strict v1 encode/decode;
- connect the server only to the typed in-process provider;
- enforce one-resource, size, timeout, unavailable, and unsupported rules; and
- add unit and controlled socket tests.

### SIM-P2B — Public CLI adapter

- add `hiyelx runtime preview --session <SESSION>`;
- map exact exit codes and sanitized errors;
- render only validated P1 canonical JSON; and
- add unit and real owner subprocess coverage.

### SIM-P2C — Installed-wheel and portability acceptance

- extend the existing verifier with the eight-marker journey;
- preserve the 21-line RTO prefix;
- update the macOS focused selection to execute preview tests;
- run local full quality gates; and
- integrate only after bounded review, then require Ubuntu and macOS Intel
  success on the exact commit.

SIM-P3 founder acceptance and Studio handoff remain separate.

## 16. Founder decisions

Each decision was approved independently by the founder on `2026-10-24`.

1. **Additive protocol v1:** keep version `1` because existing envelopes and
   status/stop shapes are unchanged.

   Approval state: `Approved by founder on 2026-10-24.`
2. **JSON-only public command:** use `runtime preview --session` without a text
   mode or `--json` switch.

   Approval state: `Approved by founder on 2026-10-24.`
3. **Private wrapped reply:** keep session/protocol metadata private and render
   only the nested validated snapshot publicly.

   Approval state: `Approved by founder on 2026-10-24.`
4. **One-resource Alpha bound:** require exactly one preview resource and defer
   shared multi-resource frames.

   Approval state: `Approved by founder on 2026-10-24.`
5. **Existing size plus total deadline:** keep 8192 bytes and use one three-
   second total preview I/O deadline with no retry.

   Approval state: `Approved by founder on 2026-10-24.`
6. **New exit codes:** reserve `12` for unavailable and `13` for unsupported,
   preserving all existing codes.

   Approval state: `Approved by founder on 2026-10-24.`
7. **Fixed failure vocabulary:** add only `preview_unavailable` and
   `preview_unsupported`; unexpected failures remain generic.

   Approval state: `Approved by founder on 2026-10-24.`
8. **Single verifier strategy:** extend the existing clean-wheel verifier and
   append the exact eight-marker registry.

   Approval state: `Approved by founder on 2026-10-24.`
9. **Hosted evidence:** require Ubuntu full plus macOS Intel preview-focused
   execution and the same 29-line wheel journey.

   Approval state: `Approved by founder on 2026-10-24.`
10. **Evidence separation:** keep SIM-P2 separate from founder usability,
    Studio/UI, ARM64 hosted, physical, release, and publication acceptance.

    Approval state: `Approved by founder on 2026-10-24.`

The founder approved these defaults with the exact phrase:

```text
APPROVE SIM-P2 CONTRACT DEFAULTS
```

This approval accepts and freezes the contract. It does not authorize product
implementation, commit, push, release, publication, or hardware operation;
those remain separate bounded steps.
