# RTO-4 Founder Black-Box Acceptance Evidence

## Decision

- Gate: `RTO4-FOUNDER-01` / RTO-4 Slice C
- Result: `PASS`
- Status: `ACCEPTED / INTEGRATED`
- Founder decision: `ACCEPT`
- Acceptance date: `2026-10-24`
- Participant: founder / product owner
- Candidate revision: `f4284c01dda9a35aec38979a356ffb6b9c02067b`
- Evidence integration revision: `2538398437b2438f20c6d78b6d9369221696581f`
- Wheel: `hiyelx-0.2.0a1-py3-none-any.whl`
- Wheel SHA-256: `37389fa3d1a22fde7da1544e2c43ef1394b0a5a1347d08d2adc6d597a0b2a705`
- Assistance requests after command-sheet handoff: `0`
- Blockers: `0`
- Unexpected traceback or path/config/credential leak: `0`
- Task-owned live processes after cleanup: `0`
- Task-owned artifacts after final workspace cleanup: `0`
- Journey steps completed: `8/8`
- Physical hardware operations: none

This record is founder black-box evidence for the installed-wheel Runtime
Operations Alpha workflow. It is not external-human usability evidence,
physical evidence, release authorization, or overall RTO-4 closure by itself.

## Environment and timing

- Operating system: macOS 27.0.1
- Architecture: arm64
- Python: 3.12.14
- uv: 0.12.7
- Installation: one fresh non-editable wheel in one fresh Python 3.12 virtual
  environment outside the source checkout
- Configuration: a task-owned copy of the canonical simulation configuration
- Session start: `2026-10-24T11:03:44+03:00`
- Session completion observation: `2026-10-24T11:10:14+03:00`
- Total measured duration: `00:06:30`
- Hard acceptance limit: `00:20:00`

The measured duration was below the 15–20 minute target and within the
normative at-most-20-minute pass threshold. No required journey step was
omitted, no assistance was requested, and no blocker occurred.

Machine identity, real temporary paths, process identifiers, run UUIDs,
history-row timestamps, credentials, raw configuration, and raw command output
are intentionally excluded.

## Automated candidate evidence

The founder session used the exact candidate previously exercised by GitHub
Quality gate
[`40067721268`](https://github.com/ulasusakli/hiyelx/actions/runs/40067721268):

| Surface | Result | Reviewed evidence |
|---|---|---|
| Exact revision | PASS | Hosted run head SHA matched the candidate revision |
| Ubuntu quality | PASS | Ruff passed; Pyright reported `0 errors, 0 warnings`; pytest reported `647 passed, 1 physical skipped` |
| Ubuntu installed wheel | PASS | Existing RTO-3 journey and all 12 RTO-4 markers passed |
| macOS Intel portability | PASS | GitHub-hosted `macos-15-intel`; `322 passed` |
| macOS Intel installed wheel | PASS | Existing RTO-3 journey and all 12 RTO-4 markers passed |

The required RTO-4 marker set was:

```text
rto4-wheel-built=passed
rto4-source-isolation=passed
rto4-env=passed
rto4-events=passed
rto4-interrupt=passed
rto4-crash=passed
rto4-prune=passed
rto4-multi=passed
rto4-negative=passed
rto4-sanitize=passed
rto4-cleanup=passed
rto4-automated-acceptance=passed
```

## Slice C evidence integration

This sanitized founder evidence was integrated at
`2538398437b2438f20c6d78b6d9369221696581f`. Quality gate
[`40086361304`](https://github.com/ulasusakli/hiyelx/actions/runs/40086361304)
tested that exact SHA and passed both hosted jobs:

| Surface | Job | Result |
|---|---:|---|
| Ubuntu quality and installed wheel | `120850006494` | Ruff and strict Pyright passed; pytest reported `647 passed, 1 physical skipped`; exact 21-line installed-wheel result and all `12/12` RTO-4 markers passed |
| macOS Intel portability and installed wheel | `120850006684` | GitHub-hosted `macos-15-intel` passed 322 focused tests; exact 21-line installed-wheel result and all `12/12` RTO-4 markers passed |

The cleanup markers and final `rto4-automated-acceptance=passed` marker were
present in both jobs. This hosted result accepts the integrated Slice C evidence
record; it does not convert the founder's local macOS/ARM64 session into hosted
ARM64 portability evidence.

## Founder journey

The founder received the installed-wheel command sheet, wheel/config inputs,
and fresh task-owned environment without implementation source or test names.
The founder personally completed the following sanitized command-level flow:

1. configured isolated `HOME`, temporary, control, and history locations;
2. validated the canonical simulation configuration;
3. started the simulation owner in the foreground;
4. observed the exact session, running, and control-ready lines;
5. used a second terminal to query runtime status;
6. identified the active run and its committed event prefix;
7. queried the active run and events;
8. exercised one invalid-session query and one unknown-run query;
9. stopped the owner from the second terminal;
10. observed the foreground owner stop and return to the first shell;
11. queried finalized run history and the complete event sequence; and
12. verified that the task-owned control area was empty.

## Sanitized command transcript

The founder executed the following public installed-wheel journey in this
order. The commands are recorded here in sanitized form and were not rerun for
this evidence update:

```bash
hiyelx validate-config <CONFIG>
hiyelx runtime start <CONFIG> --session founder-rto4

hiyelx runtime status --session founder-rto4
hiyelx runtime runs list --json
export RUN_ID='<RUN_ID>'
hiyelx runtime runs show "$RUN_ID" --json
hiyelx runtime events --run "$RUN_ID" --json

hiyelx runtime status --session ../private
printf 'invalid-session-exit=%s\n' "$?"

hiyelx runtime runs show 00000000-0000-4000-8000-000000000000 --json
printf 'unknown-run-exit=%s\n' "$?"

hiyelx runtime stop --session founder-rto4

hiyelx runtime runs show "$RUN_ID" --json
hiyelx runtime events --run "$RUN_ID" --json

if test -z "$(find "$HIYELX_RUNTIME_STATE_DIR" -mindepth 1 -print)"; then
  printf 'control-cleanup=passed\n'
else
  printf 'control-cleanup=failed\n'
fi
```

- `<CONFIG>` is a sanitized placeholder for the task-owned canonical
  simulation configuration.
- `<RUN_ID>` is a sanitized placeholder for the real value selected by the
  founder from the run list.
- `hiyelx` is the sanitized public form of the installed-wheel executable in
  the fresh virtual environment.
- Real paths, UUIDs, PIDs, and runtime-history timestamps are not recorded.
- The transcript contains no source-tree or private implementation command.

## Observed results

| Check | Result | Sanitized observation |
|---|---|---|
| Configuration validation | PASS | `configuration=valid` |
| Foreground readiness | PASS | Session identified; runtime running; control ready |
| Runtime status | PASS | One `sim_motor` resource running and healthy; watermark `3` |
| Active run | PASS | Incomplete active run; watermark `3` |
| Active events | PASS | Four contiguous events with sequences `0..3`; latest event `runtime_running/succeeded` |
| Invalid session | PASS | Fixed sanitized error; exit `3` |
| Unknown run | PASS | Fixed sanitized error; exit `11` |
| Cross-process stop | PASS | Stop client and foreground owner both reported stopped |
| Finalized run | PASS | `completed`; `cli_stop`; watermark `11` |
| Finalized events | PASS | Twelve contiguous events with sequences `0..11`; safe-stop and shutdown present; latest event `runtime_stopped/succeeded` |
| Control cleanup | PASS | Task-owned control area empty |
| Final workspace cleanup | PASS | No live owner and no task-owned acceptance artifact remained |

## Founder explanation

The founder explained that control state is local and ephemeral. In normal
product operation, runtime stop does not delete durable history: records in the
persistent history root remain until explicit prune. In this isolated
acceptance session, the task-owned history workspace was removed only by final
workspace cleanup after the required evidence had been observed. No cloud or
control plane is required.

The founder explicitly rejected interpreting this session as evidence of:

- physical hardware or XL430 acceptance;
- release, tag, package publication, or production readiness;
- hosted ARM64/Apple Silicon acceptance;
- hard-real-time behavior; or
- certified functional safety.

## Scope boundary

This evidence passes the RTO-4 founder black-box gate and is accepted and
integrated as Slice C at
`2538398437b2438f20c6d78b6d9369221696581f`. The synchronized six-document
Slice D closure set supplies the evidence/status reconciliation required for
overall RTO-4 acceptance without changing runtime behavior or public APIs.
This record remains founder evidence only; automated acceptance and closure
status retain their separate evidence layers.

No serial enumeration, hardware discovery, transport opening, actuator or
motor power, torque, movement, cloud service, tag, release, or publication
occurred during this session.
