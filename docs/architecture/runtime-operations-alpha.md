# Runtime Operations Alpha: RTO-1 through RTO-4

## Purpose

RTO-1 supplies the read-only operational state foundation for future Machines,
Runs, Health, Trigger, Job, Simulation/Preview, and Studio interfaces. It turns
the existing local Runtime Manager state into deterministic, immutable,
sanitized value objects without creating a GUI, network API, database, or
background worker.

RTO-4 adds no production runtime behavior or public API. It closes acceptance
for the integrated RTO-1 through RTO-3 behavior through an installed-wheel
automated matrix, hosted Ubuntu and macOS Intel/x86_64 portability, founder
black-box evidence, and synchronized closure documentation.

This is a software operations contract. It does not provide physical evidence,
an emergency stop, hard real-time behavior, or certified functional safety.

## State and snapshot contracts

`RuntimeOperations.snapshot()` returns one frozen `RuntimeOperationsSnapshot`.
Every collection is a tuple and every nested resource and event record is a
frozen value object. Repeated observations of unchanged state compare equal.

The snapshot contains:

- current `RuntimeManagerState`;
- one `RuntimeResourceSnapshot` per owned resource in deterministic startup-plan
  order;
- application-assigned resource identity, lifecycle state, health status, and
  an optional sanitized health summary;
- the immutable startup plan;
- historical successful-start order;
- currently running resources in successful-start order;
- the latest retained event sequence, or `None` before any event; and
- the complete ordered immutable event tuple.

The projection never returns a live `Resource`, settings mapping, driver or SDK
object, exception, credential, transport identifier, device path, timestamp, or
backend-provided text. Health detail is exposed only when it exactly matches a
fixed typed HIYELX fault summary. Unknown or application/backend-authored detail
is omitted while its health classification remains visible.

Runtime construction still performs the existing explicit registry factory
creation once. Taking a snapshot after construction does not invoke a factory,
start or stop a resource, issue a command, open a transport, mutate state, or
clear events.

## Event ordering

`RuntimeEventOperation` provides fixed operation names. Every event has an
instance-local monotonically increasing integer sequence beginning at zero,
typed outcome, fixed summary, and optional resource lifecycle and health state.
There is no wall-clock timestamp.

Successful startup records the runtime request, each resource attempt and
success in startup-plan order, then the running state. Startup failure records
the resource failure, rollback attempt, each rollback shutdown attempt and
result in reverse successful-start order, rollback completion, and runtime
failure. Rollback completion is recorded even when no resource had started.

Shutdown records the runtime request, each resource attempt and result in
reverse successful-start order, then stopped or failed. Existing safe-stop
request, attempt, health-degradation, result, and cleanup-completion ordering is
preserved. Events contain only fixed HIYELX summaries and never copy exception
messages.

The event high-water mark is the sequence of the final retained event. It is
`None` when the recorder is empty. The event tuple and high-water mark are read
from the same synchronous instance-local recorder during snapshot construction.

## Local ownership

One `RuntimeOperations` instance creates and exclusively owns one
`RuntimeManager` and one `LocalEventRecorder`. It exposes only four operations:

- read the current snapshot;
- explicitly start;
- explicitly safe-stop; and
- explicitly shut down.

Separate operations instances share no manager state, resources, event
sequence, or retained records. There is no global registry, polling loop,
automatic retry, reconnect, thread, scheduler, persistence, cloud dependency,
or organization/location model.

## Failure visibility

The façade does not hide manager exceptions. After a startup, rollback,
safe-stop, or shutdown failure, the caller receives the existing typed error
and can immediately obtain a snapshot. That snapshot retains manager state,
every resource lifecycle and health classification, historical startup
ownership, current active-resource order, and all events emitted before the
operation returned.

Raw exception objects remain available only through the existing internal
error/report contracts used by the direct caller. They are never copied into
the operations snapshot or its events.

## RTO-1 limitations

RTO-1 is an in-process, point-in-operation view. It does not provide atomic
coordination across concurrent caller tasks, process boundaries, persistence,
history after process exit, filtering, pagination, subscriptions, RPC/protobuf
fields, CLI lifecycle control, Trigger or Job execution, or physical hardware
validation. Callers remain responsible for serializing explicit lifecycle
operations.

RTO-2 adds the bounded local Runtime Start/Stop CLI behavior described below.
RTO-3 adds the durable local run and event history contract without changing
the immutable RTO-1 observation model. Simulation/Preview Alpha remains a
subsequent product layer over these foundations.

## RTO-2 local process workflow

RTO-2 turns the RTO-1 snapshot into one bounded cross-process workflow. The
foreground command owns the runtime and remains alive:

```text
hiyelx runtime start CONFIG_PATH --session SESSION_ID
```

Separate invocations may observe or stop that owner:

```text
hiyelx runtime status --session SESSION_ID
hiyelx runtime stop --session SESSION_ID
```

Only macOS and Linux are supported because this Alpha deliberately requires a
Unix-domain socket. There is no TCP fallback. The owner loads and validates the
configuration, rejects every model except the explicitly registered built-in
`motor.simulated`, constructs `RuntimeOperations` once, starts once, and only
then publishes readiness. It never imports a model path, constructs a hardware
driver, discovers a device, or opens a physical transport.

The `start` command remains the lifecycle authority. A stop request and
foreground Ctrl-C enter the same single cleanup transition: stop accepting new
connections, attempt `RuntimeOperations.safe_stop()`, attempt shutdown even if
safe-stop failed while shutdown remains allowed, remove only owned control
artifacts, return the sanitized result to accepted stop clients, and exit the
owner. No PID read from disk authorizes control, signaling, or cleanup.

## Session identity and ownership

`SESSION_ID` is 1–48 ASCII characters. Its first character must be a lowercase
letter or digit; remaining characters may also contain `-` and `_`. Values
containing uppercase letters, whitespace, separators, dots, non-ASCII text, or
path traversal are rejected before path construction.

For this script-friendly workflow, configured resource identities use the same
lowercase ASCII character set, with a 64-character limit. This is an RTO-2
admission rule rather than a change to the general `ResourceIdentity` contract;
it prevents line injection and accidental disclosure through status fields.

The state root is resolved in this order:

1. the absolute path in `HIYELX_RUNTIME_STATE_DIR`, when set; or
2. `/tmp/hiyelx-runtime-<effective-user-id>`.

The root and session directory are mode `0700`. The ownership lock, atomic
manifest, and control socket are mode `0600`. Every existing artifact is
checked with `lstat`; symbolic links, foreign ownership, group/other access,
unexpected file kinds, and unrelated directory entries are refused. The owner
uses an advisory exclusive lock as authority. A manifest PID is informational
only and is never used to signal a process.

The manifest contains only protocol version, session ID, effective user ID,
informational PID, and a SHA-256 fingerprint of the validated configuration.
It is written as an exclusive private temporary file, flushed, and atomically
replaced. It never contains configuration settings, credentials, resource
details, transport identifiers, or device paths. An unlocked session is stale;
only recognized private artifacts are reclaimed. A locked session is active
and a second start is refused. Ambiguous ownership is an error, not a cleanup
guess.

## Local control protocol

Protocol version `1` is an internal newline-delimited canonical JSON contract.
Object keys are sorted and compactly encoded. Each Unix-socket connection
accepts exactly one `status` or `stop` request and returns exactly one response.
Both sides require exact fields and types. Input and output are limited to 8192
bytes. Unknown commands, malformed JSON, unsupported versions, extra fields,
oversized input, and mismatched sessions receive fixed sanitized failures.
Arbitrary response messages are also rejected by the client.

A disconnected client does not change runtime state. Concurrent valid stop
requests join the same stop transition and receive the same result. The socket
is local, private, and undiscoverable by the protocol: requests cannot supply a
file path, Python object, module name, configuration, or executable content.
This protocol is not a public network API and has no compatibility commitment
beyond the RTO-2 Alpha.

## Canonical status output

For the canonical one-motor simulation immediately after startup, `status`
prints exactly:

```text
session=SESSION_ID
manager-state=running
resource-count=1
resource=sim_motor lifecycle=running health=healthy health-summary=none
successful-start-order=sim_motor
active-resource-order=sim_motor
event-high-water-mark=3
latest-event=runtime running
```

Resources follow RTO-1 startup-plan order. Order fields are comma-separated and
empty when no resource is present. A missing event or health summary is
rendered as `none`. Output never includes the socket or state path, raw
configuration, credentials, settings, transport identifiers, device paths,
exceptions, memory addresses, wall-clock values, or backend-authored text.

## Exit codes

| Code | Meaning |
| ---: | --- |
| `0` | Success |
| `2` | Invalid configuration or unsupported runtime model |
| `3` | Invalid session ID |
| `4` | Session already running |
| `5` | Session not running |
| `6` | Local control protocol or ownership-path failure |
| `7` | Runtime construction or startup failure |
| `8` | Runtime safe-stop, shutdown, or artifact-cleanup failure |
| `9` | Unsupported platform |

Every error line is fixed and sanitized. A cleanup failure is reported only
after all available ordered cleanup work and a later artifact-cleanup attempt
have run.

## RTO-3 durable run and event history

RTO-3 persists only fixed, sanitized operational records. It does not persist
raw configuration, credentials, environment values, device paths, tracebacks,
backend exceptions, or arbitrary event summaries. The configuration is
represented only by its lowercase SHA-256 fingerprint.

The ephemeral RTO-2 control root and the durable history root have different
lifetimes and are never shared:

- `HIYELX_RUNTIME_STATE_DIR` selects the private session/socket root; absent an
  override, RTO-2 uses its current-user temporary root.
- `HIYELX_RUNTIME_HISTORY_DIR` selects an absolute durable root for tests or
  explicit deployments.
- Otherwise history uses
  `$XDG_STATE_HOME/hiyelx/runtime-history`, or
  `$HOME/.local/state/hiyelx/runtime-history` when `XDG_STATE_HOME` is absent.

The history root is mode `0700`. Its lock, SQLite database, and SQLite WAL/SHM
sidecars are mode `0600`. `lstat`, type, effective-UID ownership, permission,
and exact entry-allowlist checks precede mutation. Symlinks, foreign ownership,
wrong file types, unsafe permissions, initialization remnants, and unknown
entries fail closed. No PID authorizes history access or cleanup.

### SQLite schema v1

`PRAGMA user_version` is exactly `1`. The schema is created atomically with
both tables:

- `runs` stores the canonical UUID4 run ID, session, configuration
  fingerprint, package version, platform, UTC start/end timestamps, terminal
  result/reason, and event high-water mark.
- `events` stores one sanitized RTO-1 event per `(run_id, sequence)`, including
  the fixed type/outcome/summary, derived severity, optional resource lifecycle
  and health fields, and a UTC persistence timestamp.

The event persistence timestamp is metadata, not ordering authority. Event
order is solely the contiguous sequence beginning at zero. Event batches and
the run high-water mark commit atomically in one short transaction. The foreign
key from events to runs uses cascade deletion so explicit pruning cannot expose
orphan events.

Schema opening validates the exact tables, index, columns, constraints, and
foreign key. Unknown schema objects, unsupported versions, corrupt rows, event
gaps, watermark mismatches, invalid fixed summaries, or result/reason
mismatches fail closed. There is no automatic migration or compatibility
bypass.

### Run lifecycle and failure precedence

A run is created after configuration/session admission and history
initialization but before Runtime Manager construction. Startup events are
persisted before readiness. After readiness, lifecycle snapshot deltas are
persisted at safe-stop and shutdown boundaries. Each write uses a short
`BEGIN IMMEDIATE` transaction with an SQLite busy timeout of at most one
second; there is no application-level retry or reconnect loop.

Terminal results are `completed`, `startup_failed`, `runtime_failed`,
`cleanup_failed`, `interrupted`, and the history-only `history_failed`, each
paired with its fixed stop reason. A primary startup, runtime, or cleanup
failure is never masked by a secondary history failure. Cleanup continues when
event persistence fails, and finalization is attempted at most once. If the
process is killed before finalization, the committed event prefix remains and
the run stays incomplete; RTO-3 does not infer a crash result from a PID.

### Read-only queries

The following commands open SQLite through URI `mode=ro` with
`query_only=ON` and produce output only after the complete selected result has
been decoded:

```text
hiyelx runtime runs list [--limit N] [--json]
hiyelx runtime runs show RUN_ID [--json]
hiyelx runtime events --run RUN_ID [--after SEQUENCE] [--limit N] [--json]
```

Run lists order by `started_at DESC, run_id DESC`. Event pages order only by
`sequence ASC`; `--after` is exclusive. Text field order is fixed, while JSON
is one compact ASCII-safe line with sorted keys. Missing history is an empty
run list. Unknown canonical run IDs return the fixed run-not-found result.
Unsafe, corrupt, or schema-mismatched stores return a fixed history failure and
never expose a partial row, SQLite error, path, or payload. Readers take WAL
snapshots without acquiring the writer initialization lock or creating a
store.

### Explicit retention

Retention is invoked only by:

```text
hiyelx runtime runs prune --keep N
```

All incomplete runs are retained. Among finalized runs, the newest `N` are
selected by `started_at DESC, run_id DESC`; deletion proceeds in
`started_at ASC, run_id ASC` order. The complete schema and logical store are
validated inside one `BEGIN IMMEDIATE` transaction before any candidate is
deleted, and the remaining store is validated before commit. Events are
deleted by the foreign-key cascade. Missing stores return zero deletions
without creating a directory, lock, database, WAL, or SHM file.

Prune does not run during runtime startup/shutdown, and there is no background
retention, checkpoint, or `VACUUM`. SQLite file size is therefore not promised
to shrink immediately. Full-store validation makes prune transaction duration
proportional to retained history size; this bounded Alpha tradeoff favors
fail-closed deletion over throughput.

### Concurrency and threat boundary

The advisory file lock protects only initialization/configuration and is not
held for a runtime's lifetime. Different sessions use separate RTO-2 ownership
locks and can write distinct runs to the shared WAL database. Short write
transactions serialize through SQLite; read-only commands may observe a
consistent snapshot while owners are active. Active runs remain incomplete and
cannot be pruned.

The security boundary assumes a private current-user directory at mode `0700`.
Preflight and identity rechecks fail closed against unsafe paths, but the Alpha
does not claim complete race freedom against a malicious same-UID process that
can modify that private directory. It also makes no durability claim beyond
SQLite `synchronous=FULL`, atomic initialization/publish, file and directory
fsync, and successfully committed transactions.

## Runtime Operations Alpha closure and next capability

RTO-2 remains a foreground, single-host, current-user control session. RTO-3
adds local persistence but no daemon, service installation, detached mode,
background task, polling, automatic retry, reconnect, remote access,
authentication, organization/location model, Trigger, Job, export/import,
search, subscription, or GUI. Its only runtime backend is deterministic
built-in simulation.

RTO-1 is complete at `bee98b6c48725db2e9311b30fcf8f00126f6061e`.
RTO-2 Local Runtime Process and Start/Stop CLI is complete. RTO-3 Local Events,
Run History, and Explicit Retention is complete: Slices A, B, C1, and C2 are
integrated and accepted. C2 was integrated at
`c40a66d4360272070403d14b9341ad95c455ad07`, and runner portability was
integrated at `7c402a4be4468d3e9501a8035c8df5a7d285676f`.

The
[`39493825893` Quality gate](https://github.com/ulasusakli/hiyelx/actions/runs/39493825893)
passed at the latter commit. Ubuntu reported `621 passed, 1 skipped`, with the
physical XL430 acceptance test explicitly unselected, and passed the clean
installed-wheel journey. The standard GitHub-hosted `macos-15-intel` runner
provided macOS 15 on Intel/x86_64 and passed 296 focused tests, the clean
installed-wheel RTO-3 journey, and artifact cleanup.

No hosted ARM64/Apple Silicon passing evidence was produced or required by the
current RTO-3 acceptance contract. Two earlier ARM64 runner-capacity attempts
received no runner and executed no test steps; they are infrastructure-capacity
blockers rather than product/test failures, and they are not passing evidence.

RTO-4 automated acceptance was integrated at
`f4284c01dda9a35aec38979a356ffb6b9c02067b`. Quality gate
[`40067721268`](https://github.com/ulasusakli/hiyelx/actions/runs/40067721268)
passed Ubuntu job `120794370547` with `647 passed, 1 physical skipped` and
macOS Intel job `120794370479` with `322 passed`. Both jobs produced the exact
21-line installed-wheel result, all `12/12` RTO-4 markers, cleanup evidence,
and final `rto4-automated-acceptance=passed`.

The founder black-box evidence was integrated at
`2538398437b2438f20c6d78b6d9369221696581f`. Quality gate
[`40086361304`](https://github.com/ulasusakli/hiyelx/actions/runs/40086361304)
passed Ubuntu job `120850006494` and macOS Intel job `120850006684` on that
exact SHA. The founder completed `8/8` public installed-wheel steps in
`00:06:30`, with zero assistance requests, blockers, unexpected leaks,
live-process leftovers, or task-owned artifact leftovers, and recorded
`ACCEPT`. The sanitized record is the
[`RTO-4 founder acceptance evidence`](../evidence/2026-10-24-rto4-founder-acceptance.md),
and the frozen acceptance boundary is the
[`RTO-4 acceptance contract`](runtime-operations-alpha-acceptance.md).

Runtime Operations Alpha RTO-1 through RTO-4 is complete in the
software/runtime acceptance scope. Ephemeral current-user control remains
separate from durable current-user history; normal runtime stop preserves
history until explicit prune. The runtime remains foreground-owned,
simulation-only, Unix-socket local, and independent of cloud or another
control plane. Simulation/Preview Alpha is the next product capability.

The founder session ran locally on macOS/ARM64 and is not hosted ARM64
portability evidence. Package version remains `0.2.0a1`; no new tag, release,
or package publication was created. No serial enumeration, hardware discovery,
transport opening, torque, or movement occurred. Physical hardware acceptance,
hard-real-time behavior, certified functional safety, and Physical Hardware
Proof remain outside this software evidence and on a deferred parallel track.
