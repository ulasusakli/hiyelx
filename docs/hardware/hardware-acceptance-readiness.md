# Hardware acceptance readiness

This document defines the software-side boundary that must be satisfied before
any HIYELX physical motor acceptance session. It is not evidence that a device
was connected or that physical acceptance passed. Software stop and cleanup are
best effort; they are not an emergency stop or certified functional safety.

## Safety boundary

Ordinary imports, pytest collection, configuration validation, and preflight
must not enumerate serial devices, construct a motor, open a transport, enable
torque, or send a command. Physical execution requires both:

1. exact pytest selection with `-m hardware`; and
2. the exact separate consent value
   `I_ACCEPT_PHYSICAL_OPERATION`.

The physical XL430 test additionally requires an operator confirmation that the
actuator is secured and unloaded and that a power cutoff is immediately
accessible. Merely supplying a config file or consent value is insufficient.

## Typed acceptance configuration

The internal `hiyelx.acceptance` namespace loads strict YAML or JSON with no
I/O beyond reading that named file. Missing and unknown fields, unsafe
identifiers, blank transports, invalid device IDs or baud rates, non-positive
deadlines, non-finite or inverted bounds, and bounds that do not straddle zero
are rejected. Driver-specific preflight then checks the device-ID range, baud
rate, expected model, and maximum command envelope.

The canonical software-only example is
[`../../examples/configs/hardware-acceptance-preflight.yaml`](../../examples/configs/hardware-acceptance-preflight.yaml).
Its `movement_authorized` value is deliberately `false`, and its transport is a
non-device placeholder.

## Preflight-only workflow

Run:

```bash
uv run hiyelx hardware preflight \
  examples/configs/hardware-acceptance-preflight.yaml
```

The command validates the document, resolves the explicitly registered XL430
driver without invoking its factory, verifies declared compatibility, and
prints a deterministic plan. It replaces the raw transport identifier with a
short SHA-256 reference and ends with `device-operations=none`. The command
does not search for devices, instantiate a transport, construct a Motor, or
start a Resource.

If `movement_authorized` is `true`, even preflight rejects the document unless
the separate exact value is supplied with:

```bash
uv run hiyelx hardware preflight ./operator-acceptance.yaml \
  --physical-consent I_ACCEPT_PHYSICAL_OPERATION
```

This still performs no physical operation. It only reports whether all
software authorization inputs are present.

## Physical-session workflow

A real session remains pending and must not be run until the exact bench,
operator, and evidence destination have been approved. The required harness
sequence is:

```text
validate
-> explicit consent
-> connect
-> identify expected device
-> bounded command
-> stop
-> torque disable where supported
-> close
-> evidence finalization
```

The harness accepts an injected session collaborator. Configuration,
registration, compatibility, pytest selection, consent, and command bounds are
checked before that collaborator is constructed. Each operation is bounded by
the configured positive finite deadline. Connect, identify, command, and stop
failures still lead to ordered best-effort stop, capability-dependent torque
disable, close, and sanitized evidence finalization. A cleanup failure does not
prevent later cleanup attempts.

As with RB-1, a deadline bounds caller waiting; it cannot forcibly terminate an
already-running blocking vendor call. A concrete session adapter must serialize
late completion and cleanup at its transport boundary. The generic harness does
not add retries, reconnects, watchdogs, or parallel access.

The physical XL430 test consumes an operator-owned configuration outside the
repository. It requires all of the following and remains excluded from normal
pytest:

```bash
HIYELX_PHYSICAL_OPERATION_CONSENT=I_ACCEPT_PHYSICAL_OPERATION \
HIYELX_HARDWARE_SECURED_NO_LOAD=1 \
HIYELX_HARDWARE_ACCEPTANCE_CONFIG=./operator-acceptance.yaml \
uv run pytest -m hardware tests/hardware/test_dynamixel_xl430_acceptance.py
```

Do not run this command as part of software verification. A physical power
cutoff remains mandatory because process, adapter, USB, or SDK failures can
prevent software cleanup from completing.

## Evidence capture

The sanitized plan contains only safe identifiers, numeric limits, capability
flags, and a transport fingerprint. Runtime evidence contains ordered stage
names and stable failure stages, never raw exception text or the raw transport
identifier. The blank
[`physical acceptance evidence template`](../evidence/hardware-acceptance-template.md)
must be copied outside the repository for an actual session and filled only
with reviewed, sanitized observations. A failed or interrupted session must
still record every attempted cleanup stage.

## Generic and driver-specific responsibilities

The generic workflow owns strict configuration, explicit consent, registry
resolution, command bounds, deadlines, ordered cleanup, sanitized evidence,
and fake-verifiable sequencing. It does not know a vendor SDK or device path.

The current DYNAMIXEL/XL430 profile owns model compatibility
(`XL430-W250-T`), IDs 0 through 252, supported baud rates, the software
acceptance envelope of -0.5 through +0.5 rad/s, and the requirement to disable
torque. The concrete driver continues to own Protocol 2.0, model number 1060,
control-table addresses, unit conversion, serialized SDK access, startup
rollback, and shutdown cleanup.

Future alternative hardware requires a separate driver profile and fake-backed
session adapter. No future driver or physical behavior is inferred from the
generic harness.

## Alternative-hardware intake checklist

Before implementing or selecting another reference motor, record:

- manufacturer and exact model;
- host adapter or transport;
- supported protocol;
- Python dependency and license;
- position, velocity, and torque capabilities;
- stop and torque-disable semantics;
- device-identification method;
- required power and wiring information;
- testable command bounds;
- availability of a non-hardware fake; and
- named physical acceptance owner.

An intake record is not a driver implementation or physical acceptance. The
alternative must retain the generic workflow while documenting every
vendor-specific lifecycle and cleanup difference.

## Deferred proof

XL430 physical acceptance, alternative reference-driver physical acceptance,
and Physical Hardware Proof remain pending. Runtime Operations Alpha remains
after the hardware-readiness boundary. No package, tag, release, publication,
hard-real-time, emergency-stop, or certified-safety claim follows from this
software-only readiness layer.
