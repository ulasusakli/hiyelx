# External Developer Dry-Run Evidence Template

> Complete this template only for an actual participant session. Do not record
> names, email addresses, credentials, environment-variable dumps, serial-device
> paths, or unnecessary personal information. Leave outcomes blank until
> observed.

## Session identity

- Anonymous participant code:
- Test date:
- Timezone:
- Operating system and version:
- Architecture:
- Python version:
- uv version:
- Starting commit SHA:
- Had this machine or user environment previously used HIYELX? `YES / NO / UNKNOWN`

## Timing

- Start time:
- Time of first exact SIM transcript match:
- Time to first successful SIM demo:

Time-to-first-SIM is recorded for baseline learning only. No time-based
pass/fail threshold applies until an external baseline exists.

## Commands and exit status

Record commands exactly as executed. Add rows when a command was repeated.

| Sequence | Exact command | Exit status | Expected result matched? | Notes |
|---:|---|---:|---|---|
| 1 |  |  |  |  |
| 2 |  |  |  |  |
| 3 |  |  |  |  |
| 4 |  |  |  |  |
| 5 |  |  |  |  |
| 6 |  |  |  |  |

## Required evidence checks

- Fresh clone used: `YES / NO`
- Local commit matched the intended GitHub revision: `YES / NO`
- Locked installation completed: `YES / NO`
- Configuration validation returned the documented result: `YES / NO`
- SIM demo exited successfully: `YES / NO`
- Transcript matched all 14 lines exactly: `YES / NO`
- Clean-install verification exited successfully: `YES / NO`
- Installed package was confirmed outside the source checkout: `YES / NO`
- Physical hardware operation performed: `YES / NO`

If physical hardware operation is `YES`, stop review and explain the protocol
violation without including a serial-device path.

## Assistance and documentation usability

- Number of assistance requests:
- Number of facilitator interventions:

Record every request or intervention. Do not include personal information.

| Sequence | Stage | Request or intervention category | Measured timer affected? | Outcome |
|---:|---|---|---|---|
| 1 |  |  |  |  |

Confusing, ambiguous, missing, or misleading documentation:

-

Sanitized error output:

```text

```

Remove credentials, tokens, environment dumps, personal information, serial
paths, and unnecessary machine-specific paths before saving evidence.

## Findings

Classify each finding:

- `P0`: prevents safe use or causes destructive/security-critical behavior
- `P1`: blocks the documented dry run in a supported environment
- `P2`: materially confusing or inefficient but has a documented workaround
- `OBSERVATION`: non-blocking usability note or possible improvement

| ID | Classification | Reproduction or evidence | Impact | Suggested documentation change |
|---|---|---|---|---|
| EDR- |  |  |  |  |

## Participant summary



## Facilitator review

- Every intervention recorded: `YES / NO`
- Environment restriction present: `YES / NO`
- Any unresolved P0 finding: `YES / NO`
- Any unresolved P1 finding: `YES / NO`
- Decision-gate notes:

## Final result

Select exactly one after review: `PASS / FAIL / ENVIRONMENT-BLOCKED`

- Final result:
- Rationale:

`ENVIRONMENT-BLOCKED` must never be counted as `PASS`. This template does not
constitute evidence until completed during an actual external participant
session.
