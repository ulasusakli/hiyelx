# Reliability Baseline RB-2: Safe-Stop, Health, and Local Events

RB-2 adds one bounded runtime cleanup operation, complete vendor-neutral fault
visibility for that operation and lifecycle cleanup, and optional instance-local
structured records. It preserves all existing Resource, Motor, Runtime Manager,
gRPC, simulation, registry, and XL430 contracts.

## Safe-stop contract

`RuntimeManager.safe_stop()` is valid while the manager is `RUNNING`. It uses
only resources the manager already owns. From the immutable historical
successful-start order, it visits resources in exact reverse order, ignores
non-motors, and calls the existing `Motor.stop()` operation on each currently
running motor. It does not start or reconstruct resources, reconnect a backend,
or retry a failed stop.

Every attempted motor produces an ordered immutable `SafeStopOutcome`, retained
in a `SafeStopReport`. One failure does not prevent later attempts. If any stop
fails, `RuntimeSafeStopError` is raised after all eligible motors have been
attempted and is chained from the first stop failure. When a caller supplies a
primary triggering failure, that exception remains `primary_failure` and the
raised aggregate is chained from it; cleanup failures remain available in the
report without replacing the trigger.

The first call caches its report. Repeated calls while the manager remains
running return the same successful report or re-raise a new aggregate over the
same failed report without issuing another motor command. Safe-stop does not
change Runtime Manager or Resource lifecycle state. Normal reverse-order
shutdown remains a separate operation and continues to work after safe-stop.

## Health propagation

Resource health remains an immutable latest snapshot independent of lifecycle.
RB-2 adds typed fault categories for safe-stop and lifecycle cleanup while
retaining RB-1 deadline and backend-unavailable categories. All categories
produce fixed vendor-neutral summaries:

- `deadline exceeded during <operation>`
- `backend unavailable during <operation>`
- `safe-stop failed during <operation>`
- `lifecycle cleanup failed during <operation>`

A failed motor safe-stop marks that motor `UNHEALTHY`. A non-RB-1 exception
during resource shutdown marks lifecycle cleanup unhealthy. Existing exception
chaining is preserved. Successful startup only changes initial `UNKNOWN` health
to `HEALTHY`; successful safe-stop, late backend completion, and shutdown do not
erase a previous fault. There is no automatic recovery or transition back to
healthy.

## Structured local events

An application may inject one `RuntimeEventSink` into one `RuntimeManager`.
There is no global sink or registry. `LocalEventRecorder` is the minimal
in-memory implementation and returns immutable tuple snapshots.

Each immutable `RuntimeEvent` contains a monotonically increasing instance-local
sequence, operation, typed outcome, fixed sanitized summary, and optional
resource identity, lifecycle state, and health status. Safe-stop records:

1. request,
2. each motor attempt,
3. each success or failure,
4. health degradation after a failed attempt,
5. cleanup completion.

Ordering uses the sequence and never depends on wall-clock time. Events contain
no raw exception text, traceback, credentials, device paths, vendor result
values, or arbitrary backend data. No timestamp or background task is created.

## Boundaries and deferred work

Safe-stop is a best-effort software baseline, not an emergency stop, hardware
watchdog, hard real-time guarantee, or certified functional-safety mechanism.
RB-2 adds no RPC or protobuf field and no remote lifecycle control. It does not
alter XL430 startup/shutdown ordering or move vendor SDK behavior outside the
HAL.

Retries, automatic reconnect, recovery loops, watchdogs, heartbeats, background
polling, shared DYNAMIXEL bus management, fleet telemetry, remote logging,
metrics/tracing exporters, cloud runtime dependencies, unbounded queues,
hardware fault injection, and physical acceptance remain explicitly deferred.
