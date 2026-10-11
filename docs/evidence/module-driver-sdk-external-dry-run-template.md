# Module/Driver SDK External Dry-Run Evidence Template

> Complete this blank template only during an actual external participant
> session. Preparation and internal rehearsal are not external evidence. Do not
> record names, emails, credentials, environment dumps, serial-device paths, or
> unnecessary personal or machine-specific information.

## Session identity

- Anonymous participant code:
- Date:
- Timezone:
- Operating system and version:
- Architecture:
- Python version:
- uv version:
- Facilitator-supplied intended commit SHA:
- Observed local `HEAD`:
- Observed `origin/main`:
- Prior HIYELX exposure: `NONE / LIMITED / SUBSTANTIAL / UNKNOWN`

## Timing

- Start time immediately before clone:
- Completion time after all clean installed checks:
- Time to first scaffold creation:
- Time to first generated-test pass:
- Time to first clean installed import:
- Total measured duration:

Timing establishes a baseline only. No time-based pass/fail threshold applies.

## Commands and exit statuses

Record every command exactly as executed, including repeats. Add rows as needed.

| Sequence | Exact command | Exit status | Expected result matched? | Sanitized notes |
|---:|---|---:|---|---|
| 1 |  |  |  |  |
| 2 |  |  |  |  |
| 3 |  |  |  |  |
| 4 |  |  |  |  |
| 5 |  |  |  |  |

## Required package and scaffold evidence

- Fresh clone used: `YES / NO`
- Local and `origin/main` SHAs matched the intended SHA: `YES / NO`
- Locked development installation completed: `YES / NO`
- Installed HIYELX CLI generated the scaffold: `YES / NO`
- Six-file layout matched exactly: `YES / NO`
- Generated pytest result:
- Generated Ruff result:
- Generated Pyright result:
- HIYELX wheel filename:
- External-driver wheel filename:
- External package version:
- Exact HIYELX dependency:
- Automated external-driver verifier result:

Exact generated layout observed:

```text

```

## Clean import evidence

Record paths relative to the symbolic `$CLEAN_ENV`. Do not include a home
directory, username, or other personal path.

- HIYELX import resolution:
- Participant-driver import resolution:
- Both imports outside the HIYELX and driver source trees: `YES / NO`

Sanitized output:

```text

```

## Usability questions

Answer in the participant's own words.

1. Which generated file should contain vendor-specific implementation?


2. Which public HIYELX `Motor` contract must that implementation satisfy?


3. How are strict driver-owned settings defined?


4. What is the registration function and stable model name?


5. Why is registration explicit and application-owned?


6. Why does the YAML model name not load Python code automatically?


7. Which version belongs to HIYELX, which belongs to the external driver, and
   what is the exact dependency relationship?


8. Which results are software-only evidence?


9. Why must the compliance harness never receive a physical production backend?


## Assistance and interventions

- Number of assistance requests:
- Number of facilitator interventions:

| Sequence | Stage | Request or intervention | Documented before help? | Outcome |
|---:|---|---|---|---|
| 1 |  |  |  |  |

## Documentation findings

- `P0`: destructive, security-critical, or unsafe protocol defect
- `P1`: blocks the documented workflow in a supported environment
- `P2`: materially confusing or inefficient with a viable workaround
- `OBSERVATION`: non-blocking usability note

| ID | Classification | Evidence or reproduction | Impact | Suggested correction |
|---|---|---|---|---|
| HCA-SDK-5- |  |  |  |  |

Sanitized error output:

```text

```

## Environment blockers and protocol integrity

- Genuine environment blocker:
- Package-index, DNS, Python, permission, platform, or loopback restriction:
- Protocol violation:
- Undocumented facilitator intervention occurred: `YES / NO`
- Physical hardware, serial, torque, or movement operation occurred: `YES / NO`

If a physical operation occurred, stop review and record the protocol violation
without including device or serial paths.

## Participant summary



## Facilitator review

- Every request and intervention recorded: `YES / NO`
- Required usability answers correct: `YES / NO`
- Any unresolved P0: `YES / NO`
- Any unresolved P1: `YES / NO`
- Decision-gate notes:

## Final result

Select exactly one after review: `PASS / FAIL / ENVIRONMENT-BLOCKED`

- Final result:
- Rationale:

`ENVIRONMENT-BLOCKED` is never a pass. This file is not evidence until an
actual external participant completes it.

## Founder acceptance

- Founder decision:
- Decision date:
- Notes:
