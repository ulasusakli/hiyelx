# gRPC Boundary

The PRE-SEED gRPC boundary is a local adapter over an already-running
`RuntimeManager`. It neither creates nor owns resources and it never starts,
stops, restarts, or recovers the runtime. The transport owns only its own gRPC
server lifecycle.

## Protocol contract

`proto/hiyelx/v1/motor.proto` is the source of truth. Its protobuf package is
`hiyelx.v1`, and `MotorService` exposes four unary methods:

- `ListMotors` lists owned `Motor` resources in lexical identity order.
- `GetMotorState` returns one identity, angular position in radians, angular
  velocity in radians per second, and a protocol-defined lifecycle enum.
- `ApplyMotorCommand` applies a finite angular velocity in radians per second.
  Positive, negative, and zero velocities are valid.
- `StopMotor` uses the existing Motor API to command zero velocity.

Resource identities cross the boundary as strings. The protocol exposes no
Python class path, registry factory, model settings, configuration document,
or vendor-specific type. It has no resource creation or Runtime Manager
lifecycle RPCs.

## Domain translation and status mapping

The adapter resolves every named resource with `RuntimeManager.get_resource`,
checks the resolved object against the existing `Motor` contract, and uses
`MotorCommand` and `MotorState` for validation and behavior. It does not access
or mutate resource or manager internals. All motor RPCs require the manager to
already be `RUNNING`.

| Condition | gRPC status | Client detail |
|---|---|---|
| Blank identity | `INVALID_ARGUMENT` | `identity must not be blank` |
| Non-finite velocity | `INVALID_ARGUMENT` | `angular velocity must be finite` |
| Unknown identity | `NOT_FOUND` | Includes only the requested identity |
| Owned resource is not a Motor | `FAILED_PRECONDITION` | Includes only the identity |
| Motor lifecycle rejects a command | `FAILED_PRECONDITION` | Includes only the identity |
| Runtime Manager is not running | `UNAVAILABLE` | `runtime is not running` |
| Operation deadline expires | `DEADLINE_EXCEEDED` | `operation deadline exceeded` |
| Expected backend failure | `UNAVAILABLE` | `resource backend is unavailable` |
| Unexpected failure | `INTERNAL` | `internal server error` |

The mapping is centralized in `hiyelx.rpc.status`. Unexpected exception text,
tracebacks, paths, and configuration contents are never returned to clients.
Normal gRPC cancellation is not intercepted.

## Transport ownership and security boundary

`MotorGrpcServer` has explicit `start_transport()` and `stop_transport()`
operations to distinguish transport lifecycle from robot-runtime lifecycle.
Its default address is `127.0.0.1`, port `0` is supported, and the selected
port is inspectable after binding. This milestone accepts only literal IPv4
loopback addresses.

The server is unauthenticated and unencrypted. Loopback-only binding is the
PRE-SEED security boundary; it is not suitable for remote or Internet-facing
deployment. Starting the transport never starts the Runtime Manager, and
stopping it never shuts the manager down.

## Generated code

Regenerate committed Python modules and typing stubs with:

```bash
uv run python scripts/generate_proto.py
```

Verify that committed output matches the schema without changing files with:

```bash
uv run python scripts/generate_proto.py --check
```

Generated output lives in `src/hiyelx/rpc/generated` and must not be edited by
hand. The script stages the source at its Python package path so generated
imports remain stable without introducing another generation platform.

## Deliberately deferred

Authentication, authorization, TLS, remote binding, streaming RPCs, service
discovery, reflection, client deadline negotiation, retries, recovery policy,
runtime lifecycle control, configuration mutation, and arbitrary resource
invocation remain out of scope. RB-1 maps resource-owned operation deadline
failures but does not add a new protobuf field or client-configurable timeout.
