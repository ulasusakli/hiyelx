# Runtime Manager

`RuntimeManager` is the single-use local composition and lifecycle boundary. It
receives an already validated `RuntimeConfig` and an explicitly populated
`ModelRegistry`. It validates the full dependency graph before invoking any
factory, then creates and exclusively owns one resource instance per configured
identity. Creation never starts resources.

The manager lifecycle is:

```text
NEW -> STARTING -> RUNNING -> STOPPING -> STOPPED
          |                       |
          +--------> FAILED <-----+
```

Dependencies are required local resource identities. Every dependency starts
before its dependent. Planning uses the lexicographically smallest available
identity at each topological-sort step, so the resulting immutable plan is
independent of document order. Missing references, duplicate dependencies,
self-dependencies, and cycles fail before resource construction.

Startup is sequential. A resource is recorded only after its existing async
`start()` completes. If startup fails, no later resource is attempted and every
previously started resource is shut down in reverse successful-start order.
Rollback continues after cleanup failures. The primary startup error remains
the raised error's cause, while ordered rollback details remain inspectable.

Normal shutdown is also sequential and uses the exact reverse successful-start
order. Every resource receives a shutdown attempt even when an earlier attempt
fails. Ordered failures retain their underlying exceptions. Successful startup
and shutdown end in `RUNNING` and `STOPPED`; any startup, rollback, or shutdown
failure leaves the manager in `FAILED`.

The manager is deliberately single-use. Resources apply their own RB-1 startup
and shutdown deadline policies; the manager preserves those failures through
its existing startup, rollback, and shutdown error contracts. Manager-level
retry, recovery, parallel startup, scheduling, signal handling, and background
work remain deferred. Runtime ownership does not add networking, cloud
coordination, dependency injection, or dynamic model discovery.
