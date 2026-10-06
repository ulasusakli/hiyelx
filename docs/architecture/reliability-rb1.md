# Reliability Baseline RB-1: Operation Deadlines and Fault Visibility

RB-1 adds bounded waiting and vendor-neutral fault visibility to operations
HIYELX already owns. It does not add a scheduler, retry policy, recovery loop,
or background polling.

## Deadline ownership

`OperationDeadlinePolicy` is an immutable resource policy expressed in seconds.
Every value must be positive and finite, and invalid policies fail during
construction before lifecycle work or I/O begins. The deterministic defaults
are:

| Operation | Default |
|---|---:|
| Resource startup | 20 s |
| Resource shutdown | 10 s |
| Motor command | 3 s |
| Motor state read | 3 s |
| One blocking driver transport operation | 2 s |

Resource startup and shutdown own their outer deadlines. The Motor contract
owns command and state-read deadlines. The XL430 driver additionally bounds
each blocking SDK call behind its typed transport seam. Policies are injected
per resource; there is no mutable global policy, environment expansion, or
configuration side effect.

The public Motor method signatures remain unchanged. Simulation uses the same
Motor deadline layer but retains deterministic explicit-time physics and does
not introduce wall-clock advancement.

## Errors and health

`OperationDeadlineExceeded` carries immutable `OperationTimeoutDetails`:
resource identity, stable operation name, configured seconds, and the resource
lifecycle state observed when the operation began. Its cause is the original
timeout. `BackendUnavailableError` is the vendor-neutral marker used by
translated communication failures; DYNAMIXEL SDK exceptions and objects remain
below the driver boundary and translated driver errors preserve their causes.

An expected timeout changes Resource health to `UNHEALTHY` with the stable
summary `deadline exceeded during <operation>`. An expected communication
failure uses `backend unavailable during <operation>`. Health snapshots remain
immutable and do not contain device paths, SDK result values, exception text,
or stack information. Successful startup publishes `HEALTHY` only from the
initial `UNKNOWN` state, so a later completion cannot silently erase a recorded
fault.

Startup or shutdown timeout still follows the existing lifecycle contract and
ends in `FAILED` through `ResourceStartupError` or `ResourceShutdownError`.
Command and read failures do not invent a new lifecycle transition: the
resource remains in its existing lifecycle state but is visibly unhealthy.
There is no automatic return to healthy state.

## Late blocking calls

Cancellation of `asyncio.to_thread()` cannot terminate a DYNAMIXEL SDK call
already running in a worker thread. On timeout the caller receives the typed
failure immediately, while the internal transport runner retains the per-port
serialization lock until that SDK call actually returns. Cleanup or another
operation may wait for that lock but cannot access the port concurrently. A
late result is consumed internally and cannot update Resource lifecycle,
health, or the primary reported failure.

This prevents a serialization race; it does **not** guarantee thread
termination or bound how long an uninterruptible vendor call occupies its
worker thread. Hardware watchdogs and stronger process isolation are outside
RB-1.

## gRPC mapping

The centralized adapter mapping adds:

| Domain condition | gRPC status | Client detail |
|---|---|---|
| Operation deadline expiry | `DEADLINE_EXCEEDED` | `operation deadline exceeded` |
| Expected backend/communication failure | `UNAVAILABLE` | `resource backend is unavailable` |

Existing validation, lookup, lifecycle, and runtime-state mappings remain
unchanged. Unexpected failures remain sanitized `INTERNAL` responses.

## Non-guarantees and deferred work

RB-1 is not hard real-time behavior, certified functional safety, a hardware
watchdog, guaranteed worker-thread termination, or an emergency stop. It adds
no retries, reconnect, shared-bus coordination, background polling, remote
telemetry, or metrics backend. Safe-stop orchestration, broader health
propagation, and local structured lifecycle/fault events are explicitly left
to RB-2.
