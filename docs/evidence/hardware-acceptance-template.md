# Physical Motor Acceptance Evidence — Blank Template

Copy this blank template for one approved physical session. Do not fill it from
software-only verification, and do not commit personal identity, personal
paths, credentials, tokens, environment dumps, or raw backend exceptions.

## Decision

- Session identifier:
- Date:
- Operator role:
- Acceptance owner:
- Repository commit:
- Result: `PASS / FAIL / ENVIRONMENT-BLOCKED / NOT RUN`
- Physical acceptance scope:
- Physical Hardware Proof claimed: `NO`

## Exact hardware

- Manufacturer:
- Motor exact model:
- Host adapter or transport:
- Protocol:
- Firmware assumptions:
- Device identifier:
- Baud rate, if applicable:
- Power supply:
- Wiring reference:
- Mechanism secured and unloaded: `YES / NO`
- Physical power cutoff accessible: `YES / NO`

## Software authorization

- Explicit `-m hardware` selection observed: `YES / NO`
- Exact physical-operation consent observed: `YES / NO`
- Typed configuration validation: `PASS / FAIL`
- Registered driver resolution: `PASS / FAIL`
- Expected-model compatibility: `PASS / FAIL`
- Sanitized preflight output:

```text
PASTE SANITIZED PREFLIGHT OUTPUT HERE
```

## Bounded operation

- Allowed command bounds:
- Requested command:
- Operation deadline:
- Movement authorized: `YES / NO`
- Raw transport identifier excluded from evidence: `YES / NO`

## Ordered sequence

Record `PASS`, `FAIL`, `NOT ATTEMPTED`, or `NOT SUPPORTED` for each stage.

| Stage | Result | Sanitized observation |
|---|---|---|
| Validate | | |
| Explicit consent | | |
| Connect | | |
| Identify expected device | | |
| Bounded command | | |
| Stop | | |
| Torque disable | | |
| Close | | |
| Evidence finalization | | |

## Cleanup and emergency boundary

- Stop attempted before close: `YES / NO`
- Torque disable attempted where supported: `YES / NO / NOT SUPPORTED`
- Close attempted despite earlier failure: `YES / NO / NOT APPLICABLE`
- Motor power removed after session: `YES / NO / NOT APPLICABLE`
- Software stop described only as best effort: `YES / NO`
- Emergency or certified-safety claim made: `NO`

## Findings

- P0:
- P1:
- P2:
- Observations:
- Environment blockers:
- Assistance or intervention:

## Review

- Operator review:
- Acceptance-owner review:
- Founder review:
- Physical acceptance granted: `YES / NO`
- Remaining limitations:
