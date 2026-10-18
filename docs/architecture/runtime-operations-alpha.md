# Runtime Operations Alpha: RTO-1 and RTO-2

## Purpose

RTO-1 supplies the read-only operational state foundation for future Machines,
Runs, Health, Trigger, Job, Simulation/Preview, and Studio interfaces. It turns
the existing local Runtime Manager state into deterministic, immutable,
sanitized value objects without creating a GUI, network API, database, or
background worker.

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
RTO-3 will add local event access and run history under separately defined
retention and storage contracts. Simulation/Preview Alpha remains a subsequent
product layer over these read-only state foundations.

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

## RTO-2 limitations and next capabilities

RTO-2 is a foreground, single-host, current-user control session. It adds no
daemon, service installation, detached mode, background task, polling,
automatic retry, reconnect, persistence, durable event history, remote access,
authentication, organization/location model, Trigger, Job, or GUI. Its only
runtime backend is deterministic built-in simulation.

RTO-1 is complete at `bee98b6c48725db2e9311b30fcf8f00126f6061e`.
RTO-2 Local Runtime Process and Start/Stop CLI is the active capability. RTO-3
will add Local Events and Run History; RTO-4 will close Runtime Operations Alpha
acceptance. Simulation/Preview Alpha follows as a product layer. Physical
hardware acceptance and Physical Hardware Proof remain a deferred parallel
track and do not block these software capabilities. Any physical-validation
claim still requires separate reviewed physical evidence.
