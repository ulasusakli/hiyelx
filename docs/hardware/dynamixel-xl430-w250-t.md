# DYNAMIXEL XL430-W250-T reference driver

This is HIYELX's single PRE-SEED real-motor reference. It deliberately supports
only one TTL XL430-W250-T on one serial port. Shared-bus ownership and other
DYNAMIXEL models are deferred.

## Fixed bench platform

- DYNAMIXEL XL430-W250-T, TTL variant
- U2D2 USB-to-TTL adapter
- U2D2 Power Hub
- Regulated 12 V / 5 A motor supply
- DYNAMIXEL Protocol 2.0
- Device ID 1 and 57,600 baud by default
- Expected model number 1060

Connect the U2D2 TTL connector to the actuator through the Power Hub. Connect
USB to the host and supply the Power Hub separately with regulated motor power;
USB does not power the actuator. Verify polarity and wiring before applying
power. Secure the actuator with no attached load and keep a physical power
cutoff within reach.

## Configuration and registration

Applications select the driver by the stable model name
`motor.dynamixel.xl430_w250_t`. Registration is explicit and performs no I/O:

```python
registry = ModelRegistry()
register_dynamixel_xl430_motor(registry)
```

The settings object requires a non-blank `device`. `motor_id` defaults to `1`
and accepts 0 through 252. `baud_rate` defaults to `57600` and accepts only
rates supported by this model. `max_abs_velocity_rad_s` defaults to `0.5` and
must be positive and finite. Unknown fields are rejected. Protocol 2.0 and
model number 1060 are fixed by the concrete model and cannot be configured.

Example (replace the device path with the local port):

```yaml
schema_version: "1"
resources:
  - identity: reference_motor
    model: motor.dynamixel.xl430_w250_t
    settings:
      device: /dev/tty.usbserial-REFERENCE
      motor_id: 1
      baud_rate: 57600
      max_abs_velocity_rad_s: 0.5
```

Configuration validation and registry construction do not open or discover
hardware. The Runtime Manager owns lifecycle startup and shutdown.

## Control-table contract and conversions

| Item | Address | Size | Driver use |
|---|---:|---:|---|
| Model Number | 0 | 2 bytes | Verify value 1060 during startup |
| Operating Mode | 11 | 1 byte | Set Velocity Control Mode, value 1 |
| Torque Enable | 64 | 1 byte | Disable during setup; enable when ready |
| Hardware Error Status | 70 | 1 byte | Require zero before enabling torque |
| Goal Velocity | 104 | 4 bytes | Write commands |
| Present Velocity | 128 | 4 bytes | Read measured velocity |
| Present Position | 132 | 4 bytes | Read measured position |

The velocity unit is `0.229 rpm * 2*pi/60` radians per second. The position
unit is `0.088 degrees * pi/180` radians. Four-byte velocity and position values
are decoded as signed two's-complement integers; negative goals are encoded as
the corresponding unsigned 32-bit bit pattern. Command conversion rounds to
the nearest register unit, with exact half values away from zero. Values beyond
the documented signed Goal Velocity range of -1023 through 1023 are rejected.
The configured software limit is checked before any serial write.

## Lifecycle and I/O

Startup runs one serialized sequence: open port, configure baud, ping and check
model 1060, disable torque, select Velocity Control Mode, write zero Goal
Velocity, check Hardware Error Status, then enable torque. Any failure triggers
best-effort zero velocity, torque disable, and port close; cleanup errors remain
inspectable without replacing the primary startup failure.

Commands and state reads use the existing asynchronous `Motor` contract. Each
blocking SDK operation is offloaded from the asyncio event loop, while one
per-driver lock prevents concurrent access to the port. Reads use measured
Present Position and Present Velocity rather than cached commands.

Shutdown attempts zero Goal Velocity, torque disable, and port close in that
order, continuing after individual failures and reporting failures in the same
order. There is no retry, reconnect, reboot, watchdog, or recovery policy.

## Physical acceptance

Ordinary `uv run pytest` never authorizes hardware I/O. The physical test
requires all three external opt-ins and explicit marker selection:

```bash
HIYELX_RUN_HARDWARE=1 \
HIYELX_HARDWARE_SECURED_NO_LOAD=1 \
HIYELX_DYNAMIXEL_DEVICE=/dev/tty.usbserial-REFERENCE \
uv run pytest -m hardware tests/hardware/test_dynamixel_xl430_acceptance.py
```

Before running, confirm the actuator is secured, unloaded, and the physical
power cutoff is accessible. The test identifies model 1060, starts the real
Runtime Manager and loopback gRPC server, lists and reads the motor, commands
at most +0.3 rad/s and -0.3 rad/s for a nominal 0.25 seconds each (below the
0.5-second acceptance ceiling) with a zero command after each movement, then
independently stops transport and runtime. Its `finally`
path again attempts zero velocity, transport cleanup, torque disable, and port
closure. After completion, verify torque is disabled by confirming the unloaded
actuator can be moved freely, then remove motor power.

## Troubleshooting

- Port cannot open: verify the external device path, OS permissions, USB cable,
  U2D2 visibility, and that no other process owns the port.
- Ping fails: verify TTL wiring, separate 12 V motor power, device ID 1, baud
  57,600, and Protocol 2.0.
- Unexpected model: the connected actuator is not model number 1060; do not use
  this driver for another DYNAMIXEL family.
- Device error: remove power safely and inspect supply, load, temperature,
  wiring, and the device's Hardware Error Status before another attempt.

## Safety and reliability boundary

This is not hard real-time control and is not certified functional safety.
Software stop is not an emergency stop. Process termination, USB disconnection,
or software failure can leave motion active because watchdog and heartbeat
behavior are deferred. A physical power cutoff remains necessary. RB-1 bounds
caller waiting for driver operations and serializes late SDK completion, but
Python cannot forcibly terminate an already-running blocking SDK call. Shared
serial buses, retries, reconnect, fault recovery, monitoring, hardware
watchdogs, and automatic safe-stop policies are also deferred.
