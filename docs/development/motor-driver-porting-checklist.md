# Motor Driver Porting Checklist

Use this checklist when adapting the hardware-free scaffold to another motor.
It defines software and physical evidence boundaries; it does not certify a
driver or authorize hardware access.

## Identity, registration, and settings

- Choose one stable vendor-neutral model name, such as
  `motor.vendor.model`, and keep it independent of Python module paths.
- Expose an explicit registration function that calls
  `register_motor_driver` on an application-owned `ModelRegistry` instance.
- Do not add package scanning, entry-point discovery, dynamic imports, or
  configuration-sourced code loading.
- Define a frozen Pydantic settings model with strict types and
  `extra="forbid"`.
- Keep device addresses and vendor options inside driver-owned settings; never
  leak vendor SDK types into Resource, Motor, runtime, or application APIs.

## Motor and transport boundary

- Preserve the application-level Motor API in SI units: radians and radians
  per second.
- Validate finite values, command limits, register ranges, signs, rounding,
  saturation policy, and unit conversions before transport I/O.
- Keep blocking vendor calls off the asyncio event loop.
- Serialize transport access so concurrent commands, reads, lifecycle work,
  and late blocking completions cannot race.
- Apply explicit operation deadlines without assuming a worker thread can be
  forcibly terminated.
- Translate vendor failures into typed, sanitized driver errors and preserve
  original exceptions through `__cause__`.

## Lifecycle and cleanup

- Document exact startup ordering, including when communication opens, modes
  change, zero commands are written, and torque could be enabled.
- On startup failure, preserve the primary error and perform ordered
  best-effort rollback without replacing it with cleanup failures.
- Implement `stop()` through the existing Motor zero-velocity command while
  respecting the backend's measured-state semantics.
- Document shutdown ordering and continue required cleanup attempts after one
  fails; retain deterministic ordered failure evidence.
- Treat software stop as best effort, not an emergency stop.

## Software-only evidence

- Build a deterministic fake transport or in-memory Motor with no serial,
  network-discovery, torque, or physical-motion behavior.
- Add driver-controlled failure injection for startup, command, state, stop,
  shutdown, and cleanup paths that matter to that transport.
- Run `run_motor_compliance` only with an explicitly declared
  `software_only=True` fixture.
- Supply command-effect and stopped-state predicates appropriate to the fake;
  do not assume physical feedback immediately equals the commanded velocity.
- Verify strict settings rejection, non-Motor builder rejection, preserved
  causes, and ordered cleanup events.
- Keep tests deterministic: no wall-clock sleeps, randomness, external
  network, package discovery, or physical devices.
- Preserve SIM/REAL application-level parity through the same Motor,
  configuration, Runtime Manager, and gRPC contracts.

## Physical acceptance remains separate

- Create a separate, explicit opt-in physical test plan for the exact actuator,
  adapter, power supply, protocol, firmware assumptions, and operating limits.
- Secure the mechanism without load and keep a physical power cutoff within
  immediate reach before any powered test.
- Require deliberate environment opt-ins and explicit physical-test selection;
  ordinary software suites must remain hardware-free.
- Record real startup, positive/negative/zero command, measured state, stop,
  shutdown, torque-disable, and power-removal evidence before making a physical
  acceptance claim.
- Treat shared-bus ownership and multi-axis coordination as a separate design
  problem; do not infer them from a single-motor driver.

Passing software compliance does not establish hard-real-time behavior, an
emergency stop, certified functional safety, broad hardware compatibility, or
physical acceptance.
