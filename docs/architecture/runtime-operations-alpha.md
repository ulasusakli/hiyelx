# Runtime Operations Alpha: RTO-1

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

## Current limitations

RTO-1 is an in-process, point-in-operation view. It does not provide atomic
coordination across concurrent caller tasks, process boundaries, persistence,
history after process exit, filtering, pagination, subscriptions, RPC/protobuf
fields, CLI lifecycle control, Trigger or Job execution, or physical hardware
validation. Callers remain responsible for serializing explicit lifecycle
operations.

RTO-2 will add bounded local Runtime Start/Stop CLI behavior. RTO-3 will add
local event access and run history under separately defined retention and
storage contracts. Simulation/Preview Alpha remains a subsequent product layer
over these read-only state foundations.
