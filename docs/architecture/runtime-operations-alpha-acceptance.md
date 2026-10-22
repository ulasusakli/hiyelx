# RTO-4 Runtime Operations Alpha Acceptance Contract

> - **Status:** Accepted / Frozen — RTO-4 Slice A
> - **Founder approval:** `APPROVE RTO-4 CONTRACT DEFAULTS`
> - **Approval date:** `2026-10-22`
> - **Evidence baseline:** `439c3525adb66b880d57590e33f3c2c6837b1883`
> - **Package version:** `0.2.0a1`
>
> This approval accepts and freezes the contract only. It does not start RTO-4
> acceptance execution or accept RTO-4 overall.

Normative words such as **must** and **must not** describe the accepted exit
contract. They do not claim that the corresponding RTO-4 evidence exists.

### Status vocabulary

Slice A integration accepts and freezes the contract, but it does not start
automated acceptance execution. The target state immediately after an
authorized and successful Slice A integration is:

```text
RTO-4 CONTRACT ACCEPTED: YES
RTO-4 ACCEPTANCE EXECUTION STARTED: NO
RTO-4 ACCEPTED: NO
READY FOR RTO-4 SLICE B: YES
```

The current `README.md` and `PRESEED.md` wording that RTO-4 is next and not
started is therefore not contradictory while acceptance execution has not
begun. Only authorized Slice B implementation changes
`RTO-4 ACCEPTANCE EXECUTION STARTED` to `YES`. Contract acceptance alone does
not imply automated, founder, or overall RTO-4 acceptance.

## Existing contract and evidence inventory

The contract is derived from the following current sources:

- [`README.md`](../../README.md) and [`PRESEED.md`](../../PRESEED.md) define
  RTO-1, RTO-2, and RTO-3 as complete, RTO-4 as next and not started, and
  physical acceptance as a separate pending track.
- [`runtime-operations-alpha.md`](runtime-operations-alpha.md) defines the
  RTO-1 snapshot, RTO-2 foreground-owner/control, and RTO-3 durable-history
  contracts and stable runtime exit codes.
- [`clean-install-and-demo.md`](../development/clean-install-and-demo.md) and
  [`verify_clean_install.py`](../../scripts/verify_clean_install.py) define the
  clean, non-editable installed-wheel journey and its bounded cleanup.
- [`cli.py`](../../src/hiyelx/cli.py),
  [`control.py`](../../src/hiyelx/runtime/control.py),
  [`history.py`](../../src/hiyelx/runtime/history.py), and
  [`events.py`](../../src/hiyelx/runtime/events.py) are the implemented CLI,
  process-control, history, and sanitized-event contracts.
- [`test_runtime_cli.py`](../../tests/integration/test_runtime_cli.py) and
  [`test_verify_clean_install.py`](../../tests/unit/test_verify_clean_install.py)
  distinguish subprocess integration coverage from installed-wheel verifier
  coverage.
- [`ci.yml`](../../.github/workflows/ci.yml) is the current hosted execution
  surface.

Current evidence answers the inventory questions as follows:

1. **Implemented journeys.** RTO-1 supplies immutable sanitized runtime
   snapshots and ordered events. RTO-2 supplies a foreground simulation owner,
   bounded readiness, cross-process status/stop, ordered safe-stop/shutdown,
   strict private Unix-socket control, and owned control-artifact cleanup.
   RTO-3 supplies active and finalized run queries, persisted event pages,
   canonical text/JSON, explicit prune, shared history across processes, and
   fail-closed local-store validation.
2. **Installed-wheel evidence.** The current verifier builds and installs one
   non-editable wheel, rejects checkout imports, validates the canonical
   configuration and demo, checks missing history, starts two sequential
   owners, queries active/finalized history and events from separate processes,
   stops each owner, checks text/JSON cursor behavior, prunes one finalized run,
   and verifies task-owned artifact cleanup.
3. **Already hosted.** Quality gate
   [`39493825893`](https://github.com/ulasusakli/hiyelx/actions/runs/39493825893)
   accepted RTO-3 at `7c402a4be4468d3e9501a8035c8df5a7d285676f`:
   Ubuntu passed Ruff, Pyright, `621 passed, 1 physical skipped`, and the
   clean-wheel journey; GitHub-hosted `macos-15-intel` passed 296 focused tests
   and the clean-wheel journey. Current-main run
   [`39673811095`](https://github.com/ulasusakli/hiyelx/actions/runs/39673811095)
   repeated those critical jobs successfully at the baseline SHA above.
4. **Source-tree-only evidence.** Concurrent multi-session isolation,
   near-simultaneous finalization, SIGINT finalization, forced-process-death
   committed-prefix behavior, raw malformed/oversized protocol rejection,
   unsafe control artifacts, corrupt/schema-mismatched history, bounded
   database contention, and injected cleanup failures are covered by
   integration or unit tests but are not all exercised by the installed-wheel
   verifier.
5. **Human evidence.** No RTO-4 founder black-box session or sanitized RTO-4
   evidence record exists. Technical CI success cannot supply that evidence.
6. **Undefined RTO-4 decisions.** The repository has not yet approved the
   founder-session requirement, the exact installed-wheel negative set, the
   verifier reuse strategy, RTO-4 marker names, the evidence-record format, or
   the final synchronization set.
7. **Real remaining gap.** Existing tests must retain their present names and
   provenance. RTO-4 needs only missing acceptance orchestration, installed-wheel
   coverage for the named gaps, a founder session, and a closure record. It does
   not need existing RTO-1–RTO-3 behavior relabeled as new functionality.

## A. Purpose

RTO-4 adds no runtime feature. It closes externally observable Alpha acceptance
for the integrated RTO-1 through RTO-3 whole.

The accepted journey must prove one coherent Runtime Operations Alpha that:

- runs from an installed, non-editable wheel;
- is local-first and simulation-backed;
- uses a foreground owner;
- permits status and stop from separate processes;
- exposes durable run and event history;
- provides explicit retention/prune;
- emits fixed, sanitized failure and cleanup results; and
- leaves no task-owned process or ephemeral control artifact after graceful
  completion.

RTO-4 acceptance is software/runtime acceptance only. It is not physical,
release, publication, production-readiness, hard-real-time, or safety
certification evidence.

## B. In scope

The accepted acceptance scope is:

- clean Python 3.12, non-editable wheel installation;
- source-tree import rejection;
- canonical `motor.simulated` configuration validation;
- foreground runtime owner startup and bounded readiness;
- status from a separate process;
- active run visibility and its committed event prefix;
- stop from a separate process;
- ordered safe-stop and shutdown, owner exit, and control-artifact cleanup;
- finalized run queries;
- event cursor, limit, pagination, ordering, and canonical text/JSON output;
- explicit deterministic retention/prune;
- sequential cross-process persistence;
- concurrent multi-session isolation and independent stopping;
- SIGINT cleanup and `interrupted` finalization;
- forced-process-death committed-prefix and incomplete-run behavior;
- invalid session, configuration, runtime model, run, cursor, and limit input;
- duplicate active and missing session behavior;
- missing, unsafe, ambiguous, wrong-type, symlinked, unknown-artifact,
  schema-mismatched, and corrupt local-store behavior;
- malformed and oversized private control messages;
- bounded database/initialization-lock contention;
- fixed exit codes, sanitized stderr, no partial query stdout, and cleanup
  failure precedence;
- Ubuntu full quality plus installed-wheel execution; and
- GitHub-hosted macOS 15 Intel/x86_64 focused portability plus installed-wheel
  execution.

## C. Explicitly out of scope

RTO-4 must not claim or exercise:

- physical hardware or XL430 acceptance;
- serial enumeration, discovery, transport opening, torque, or movement;
- ARM64/Apple Silicon passing evidence;
- Windows support;
- daemon or service installation;
- detached or background runtime ownership;
- TCP or remote control;
- cloud or control-plane dependency;
- authentication or organization/location models;
- Trigger or Job;
- Studio or another GUI;
- automatic retry or reconnect;
- automatic retention;
- database migration, repair, checkpoint, or `VACUUM`;
- PID-derived crash classification;
- telemetry upload;
- hard-real-time or certified-safety claims;
- a tag, release, registry publication, or package-version change; or
- mandatory issue, branch, pull-request, or ADR process.

## D. Evidence layers

Every acceptance claim must use exactly one primary evidence class. Supporting
evidence may be linked, but it must not change the primary classification.

| Code | Evidence class | Meaning | Permitted conclusion |
| --- | --- | --- | --- |
| E1 | Existing automated evidence | Already implemented and currently covered by named tests, the installed-wheel verifier, and/or successful hosted jobs. | The existing behavior is evidenced at its stated surface only. |
| E2 | RTO-4-specific automated acceptance evidence required | Existing behavior lacks the required installed-wheel, subprocess, fault, marker, or hosted acceptance surface. | The RTO-4 automated gate may pass after the missing evidence is integrated and run. |
| E3 | Founder black-box acceptance required | A founder executes the public CLI without reading implementation source and records the bounded session. | Founder acceptance only; not external-human usability or physical evidence. |
| E4 | Out of scope / separately evidenced | The claim belongs to physical, release, platform, or future-product work. | No RTO-4 acceptance conclusion. |

Rules:

- Unit or source-tree integration success must not be presented as
  installed-wheel evidence.
- Installed-wheel success must not be presented as founder acceptance.
- Founder acceptance must not be presented as external-human usability.
- No software evidence must be presented as physical acceptance.
- A workflow-level green badge is insufficient without exact SHA, assigned
  runner, job/step conclusions, test counts, required markers, and cleanup.

## E. Acceptance matrix

| ID | Journey/claim | Existing evidence | New evidence needed | Execution surface | Expected result | Failure classification | Exit gate |
| --- | --- | --- | --- | --- | --- | --- | --- |
| RTO4-ENV-01 | Clean non-editable wheel, Python 3.12, checkout import rejection | E1: `verify_clean_install.py` builds, installs, and checks `site-packages`. | E2: retain the check in the RTO-4 run and emit `rto4-wheel-built=passed`, `rto4-source-isolation=passed`, then `rto4-env=passed` only after their respective ENV assertions pass. | Fresh task-owned directory outside the checkout. | Exactly one `hiyelx-0.2.0a1-*.whl`; import resolves under the clean environment and outside the repository. | Product/package failure; environment-blocked only for explicit Python/package/DNS capability failure. | Exit `0`; all three ENV markers present once; no source import. |
| RTO4-START-01 | Canonical simulation owner and bounded readiness | E1: installed-wheel verifier; readiness deadline 15 s. | No new behavior; preserve this as an RTO-4 prerequisite. | Installed `hiyelx runtime start CONFIG --session SESSION`. | Three lines in order: `session=SESSION`, `runtime=running`, `control=ready`. | Product failure for wrong/partial output or timeout. | Owner remains alive after exact readiness; no stderr. |
| RTO4-STATUS-01 | Status from another process | E1: installed-wheel verifier and subprocess integration. | No new behavior; retain exact transcript check. | Separate installed CLI process. | Exit `0`; canonical eight-line one-resource status with high-water mark `3`. | Product failure. | Byte-exact stdout, empty stderr. |
| RTO4-HISTORY-01 | Active, finalized, and cross-process durable run queries | E1: installed-wheel verifier covers active/finalized records and two sequential sessions. | Preserve structural UUID/time validation and explicit first-run persistence during the second owner. | Separate installed CLI processes sharing one isolated history root. | Active result is `null`/`incomplete`; stopped result is `completed` with `cli_stop`; first run remains queryable during and after the second session. | Product/history failure. | Canonical text/JSON agree; no partial result. |
| RTO4-EVENTS-01 | Active prefix, terminal events, cursor, limit, and text/JSON | E1: installed-wheel verifier checks sequences `0..3`, then `0..11`, `--after 3`, `--limit 1`, and `--limit 1000`. | Preserve as a required RTO-4 marker group. | Installed CLI queries. | Contiguous ordering; active watermark `3`; finalized watermark `11`; after/limit results exact. | Product/history failure. | Required `rto4-events=passed`; no malformed or partial output. |
| RTO4-STOP-01 | Cross-process stop, ordered safe-stop/shutdown, owner exit | E1: installed-wheel verifier and integration tests. | Preserve owner-exit and terminal-history assertions. | Installed stop client plus foreground owner. | Stop client exits `0`; owner exits `0` within 15 s; run finalizes `completed/cli_stop`; 12 events. | Product/cleanup failure. | Stop stdout exact, both stderr streams empty, session directory absent. |
| RTO4-INTERRUPT-01 | SIGINT ordered cleanup | E1 only at source-tree subprocess integration. | E2: repeat through the installed wheel. | POSIX signal to installed foreground owner. | Owner exits `0`; stdout ends `runtime=stopped`; run is `interrupted/sigint`; sequences `0..11`; session directory absent. | Product/cleanup failure. | Required `rto4-interrupt=passed`. |
| RTO4-CRASH-01 | Forced termination preserves committed prefix without inventing a result | E1 only at source-tree subprocess integration. | E2: installed-wheel forced termination followed by safe stale-artifact recovery. | Installed foreground owner terminated by the harness. | OS signal termination (`returncode < 0`); run remains incomplete with no end/result/reason, watermark `3`, and events `0..3`; no PID-derived result. | Product/history failure if prefix mutates or a result is inferred. | Required `rto4-crash=passed`; recognized stale control state is safely reclaimed before final cleanup. |
| RTO4-PRUNE-01 | Explicit deterministic prune | E1: installed-wheel verifier and source-tree active-run coverage. | E2: retain installed sequential case and add acceptance that an active run is never deleted. | Installed CLI with at least two finalized runs and one controlled active run for the automated case. | `--keep 1` deletes only the oldest finalized run; incomplete runs and newest finalized run remain; removed run returns exit `11`. | Product/history failure. | Required `rto4-prune=passed`; no automatic prune or `VACUUM`. |
| RTO4-MULTI-01 | Concurrent session isolation | E1 only at source-tree integration, including independent stops and near-simultaneous finalization. | E2: installed-wheel two-owner orchestration. | Two installed foreground owners with distinct sessions and shared isolated history. | Both active runs are visible; stopping one leaves the other responsive; both finalize once; both session directories disappear. | Product/concurrency/cleanup failure. | Required `rto4-multi=passed`. |
| RTO4-NEGATIVE-01 | Invalid session/config/model; duplicate and missing session | E1 in CLI/unit and source-tree integration tests. | E2: installed-wheel command matrix with exact code/stdout/stderr. | Installed CLI. | Codes `3`, `2`, `2`, `4`, and `5` respectively; fixed sanitized errors; empty stdout. | Product contract failure. | Required for combined `rto4-negative=passed`; every row matches Section G exactly. |
| RTO4-NEGATIVE-02 | Malformed/oversized/unknown private control request | E1 in unit and source-tree integration tests. | E2: installed-owner wire probe; no public CLI option is added. | Private Unix socket, one raw request per connection. | Canonical failure reply; owner remains active; malformed/oversized use `invalid_request`, unknown command uses `unknown_command`. | Product protocol failure. | Required for combined `rto4-negative=passed`; exact JSON reply and no disconnect-triggered stop. |
| RTO4-NEGATIVE-03 | Invalid run/cursor/limit and missing history | E1 in CLI/unit tests; missing history is installed-wheel verified. | E2: retain missing-store checks and add installed invalid cursor/limit cases. | Installed CLI. | Run errors exit `11`; parser errors exit `2`; missing list/prune exit `0`; missing store is not created. | Product CLI/history failure. | Required for combined `rto4-negative=passed`; exact Section G outputs and zero partial stdout. |
| RTO4-NEGATIVE-04 | Unsafe permissions, symlink, wrong type, unknown or ambiguous artifact | E1 in control/history unit tests. | E2: bounded filesystem-fixture acceptance; installed CLI where safely observable. | Task-owned control/history roots only. | Control failures exit `6`; history failures exit `10`; no unrelated entry is removed or mutated. | Product ownership-path failure. | Required for combined `rto4-negative=passed`; fixed error, no leak, and no unintended mutation. |
| RTO4-NEGATIVE-05 | Schema mismatch, logical corruption, busy writer/initialization lock | E1 in history/control unit tests. | E2: deterministic fault fixtures with bounded elapsed time and rollback/no-partial-mutation checks. | Task-owned SQLite store; installed CLI plus controlled lock holder where applicable. | Corrupt/schema/busy CLI path exits `10`; write/init wait is bounded by the implemented 1 s store timeout plus harness margin. | Product history failure, not environment-blocked. | Emit combined `rto4-negative=passed` only after every RTO4-NEGATIVE row passes. |
| RTO4-SANITIZE-01 | No traceback, path, config, credential, SQLite, or backend-text leak | E1 across CLI, control, history, integration, and verifier tests. | E2: scan stdout/stderr from every RTO-4 automated case and the founder transcript. | All acceptance surfaces. | Only documented fields and fixed errors appear. | Product privacy/sanitization failure. | Required `rto4-sanitize=passed`; zero forbidden matches. |
| RTO4-CLEANUP-01 | Cleanup success and cleanup-failure precedence | E1: installed success cleanup; failure precedence through unit fault injection. | E2: verify all success paths leave zero task-owned ephemeral artifacts; retain deterministic injected cleanup-failure evidence. | Installed subprocesses plus controlled fault test. | Success leaves zero owner/control artifacts; induced cleanup failure exits `8`, reports only `error: runtime cleanup failed`, attempts all cleanup, and records `cleanup_failed/cleanup_failure` when history can finalize. | Product cleanup failure. | Required `rto4-cleanup=passed`; no live process. |
| RTO4-PORTABILITY-01 | Ubuntu full quality and installed-wheel journey | E1: successful hosted jobs at the two cited runs. | E2: run the integrated RTO-4 acceptance slice on the exact candidate SHA. | GitHub-hosted Ubuntu job. | Ruff, strict Pyright, full pytest with the physical test explicitly skipped, and all required installed-wheel/RTO-4 markers pass. | Product failure, or explicit runner/environment blocker with no acceptance credit. | Assigned runner, successful critical steps, exact counts and markers. |
| RTO4-PORTABILITY-02 | macOS Intel/x86_64 focused portability and installed-wheel journey | E1: successful `macos-15-intel` jobs at the two cited runs. | E2: run the integrated RTO-4 acceptance slice on the exact candidate SHA. | GitHub-hosted `macos-15-intel`. | Runner is assigned; focused tests and all required installed-wheel/RTO-4 markers pass. | Product failure, or runner-capacity blocker with no acceptance credit. | Label, image, x86_64 evidence, step results, counts, markers, cleanup. |
| RTO4-FOUNDER-01 | Founder can complete and explain the public workflow | No existing RTO-4 evidence. | E3: one sanitized 15–20 minute session defined in Section H. | Installed wheel and public CLI; no source inspection. | All tasks complete within 20 minutes, zero blocker, zero unexpected leak, zero remaining task-owned artifact, explicit founder accept. | Founder rejection or blocked session; never converted into automated or physical acceptance. | Sanitized evidence record integrated. |

E4 applies to every item in Section C. Those items must not be added to an
RTO-4 verifier, founder session, or completion claim.

### Required automated markers

The accepted contract requires the RTO-4 automated verifier to use exactly this
marker registry:

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

Each marker must be written only after every assertion associated with that
marker has passed. No marker may be written for a failed or
environment-blocked case. Each emitted marker is one canonical `name=passed`
line, and duplicate markers are invalid. The final
`rto4-automated-acceptance=passed` marker may be written only after the other
eleven required RTO-4 markers and all existing RTO-3 clean-wheel markers have
passed.

The final marker proves completion of the E2 automated acceptance matrix only.
It does not prove founder black-box acceptance, overall RTO-4 acceptance, or
RTO-4 completion. Full RTO-4 acceptance requires automated acceptance, founder
acceptance, evidence integration, and closure synchronization together. The
automated verifier must not emit founder or physical-acceptance markers.
Existing RTO-3 marker names and meanings remain unchanged.

## F. Canonical black-box journey

### Isolation and value rules

The automated journey must create a fresh private temporary root outside the
checkout, copy the canonical simulation configuration into it, clear
`PYTHONPATH`, `PYTHONHOME`, `VIRTUAL_ENV`, and `UV_PROJECT_ENVIRONMENT`, set
`PYTHONNOUSERSITE=1`, and point `HOME`, `TMPDIR`,
`HIYELX_RUNTIME_STATE_DIR`, and `HIYELX_RUNTIME_HISTORY_DIR` at task-owned
locations.

`REPO_ROOT`, `WORK_DIR`, `PYTHON`, `HIYELX`, `CONFIG`, `SESSION`, `RUN_ID`, and
`WHEEL` below are harness variables, not literal expected output. A UUID must be
a canonical lowercase UUID4. A timestamp must be canonical UTC with six
fractional digits and `Z`. A PID and a temporary path may be structurally
checked inside the harness but must not become a fixed expected value or a
published evidence field.

For product CLI commands, forbidden output is any traceback, absolute control
or history path, raw configuration, credential, device/transport identifier,
SQLite message, backend exception, memory address, or unrecognized free-form
text. Build/install tools may internally print task paths; the sanitized
evidence record must not copy those paths.

### Steps

| Step | Command form | Expected exit | Expected output or marker | Timeout | Cleanup responsibility |
| --- | --- | ---: | --- | ---: | --- |
| Build wheel | `uv build --wheel --no-create-gitignore --out-dir "$WORK_DIR/wheel" "$REPO_ROOT"` | `0` | Exactly one `hiyelx-0.2.0a1-*.whl`; required `rto4-wheel-built=passed`. | 180 s | Harness removes build output in final cleanup. |
| Clean install | `uv venv --python 3.12 --no-project "$WORK_DIR/venv"`, then `uv pip install --strict --python "$PYTHON" "$WHEEL"` | `0` each | Python reports `3.12.x`; installation is non-editable. | 180 s each | Harness owns and removes the environment. |
| Reject source import | `"$PYTHON" -c 'from pathlib import Path; import hiyelx; print(Path(hiyelx.__file__).resolve())'` | `0` | Captured path is under the clean environment's `site-packages` and outside `REPO_ROOT`; required `rto4-source-isolation=passed`. | 15 s | Captured path is not copied into published evidence. |
| Validate config | `"$HIYELX" validate-config "$CONFIG"` | `0` | Exactly `configuration=valid`. | 15 s | No runtime artifact may exist. |
| Start owner | `"$HIYELX" runtime start "$CONFIG" --session "$SESSION"` | Foreground process remains active | Exactly `session=SESSION`, `runtime=running`, `control=ready` in order. | One total 15 s readiness deadline | Harness registers the owner before reading readiness and owns fallback cleanup. |
| Status | `"$HIYELX" runtime status --session "$SESSION"` from another process | `0` | Exact canonical one-resource status; watermark `3`, latest event `runtime running`. | 15 s outer; product control I/O remains 3 s | Owner must remain active. |
| Active runs | `"$HIYELX" runtime runs list --json`, then `"$HIYELX" runtime runs show "$RUN_ID" --json` | `0` each | One matching run; canonical UUID4; `ended_at`, `result`, `stop_reason` are `null`; watermark `3`. | 15 s each | History persists; no cleanup yet. |
| Active events | `"$HIYELX" runtime events --run "$RUN_ID" --json` | `0` | Canonical ASCII JSON; four events with sequences `0..3`. | 15 s | Owner remains active. |
| Stop | `"$HIYELX" runtime stop --session "$SESSION"` from another process | `0` | Exactly `session=SESSION` then `runtime=stopped`. | 15 s | Stop initiates ordered safe-stop/shutdown; harness retains kill fallback. |
| Wait for owner | Harness waits for the foreground process. | `0` | Remaining stdout exactly `runtime=stopped`; stderr empty. | 15 s | If timeout occurs, verifier fails and uses bounded stop/terminate/kill cleanup. |
| Finalized run | `"$HIYELX" runtime runs show "$RUN_ID" --json` | `0` | `completed`, `cli_stop`, structural end time, watermark `11`. | 15 s | Control session directory must already be absent; durable history remains. |
| Event pagination | Text events plus `--after 3 --json`, `--limit 1 --json`, and `--limit 1000 --json` | `0` each | Text and JSON represent the same 12 events; pages contain 8, 1, and 12 events respectively. | 15 s each | No history mutation. |
| Cross-process persistence | Repeat start/stop with a distinct session against the same history root, then query both run IDs. | `0` for all CLI commands | Two distinct finalized runs, newest first; first run remains queryable. | Same per-step limits | Second owner receives the same cleanup guarantees. |
| Explicit prune | `"$HIYELX" runtime runs prune --keep 1` | `0` | Exactly `deleted-runs=1`; removed run/events exit `11`; retained run/events are unchanged. | 15 s | Prune is explicit; no `VACUUM`, repair, or automatic retention. |
| Verify cleanup | Harness checks processes and task-owned roots, then removes `WORK_DIR`. | Harness success `0` | Existing `history-artifact-cleanup=passed` and required `rto4-cleanup=passed` only after all checks and final removal. | 5 s per fallback phase | Stop, wait, terminate, then kill are bounded fallback phases; unsafe cleanup targets are refused. |

The existing final marker `clean-install=passed` remains valid only for the
existing verifier contract. The RTO-4 aggregate marker
`rto4-automated-acceptance=passed` may be emitted only under the registry rules
above, after every required E2 automated row passes and all task-owned cleanup
completes. It supplies no founder or overall RTO-4 acceptance conclusion.

## G. Negative and failure journeys

Unless noted otherwise, every CLI failure must produce empty stdout, exactly
one documented sanitized error on stderr, no partial record, and no traceback,
path, configuration, credential, SQLite text, payload, or backend exception.

| Case | Input/surface | Expected exit or reply | Required stderr/reply | Cleanup and durable-history expectation |
| --- | --- | --- | --- | --- |
| Invalid session ID | `runtime status --session ../private` and equivalent start/stop inputs | Exit `3` | `error: runtime session ID is invalid` | No path construction, control artifact, or history mutation. |
| Invalid configuration | `runtime start INVALID --session valid` | Exit `2` | `error: runtime configuration is invalid` | No session or run is created. |
| Unsupported runtime model | Valid config containing a model other than built-in `motor.simulated` | Exit `2` | `error: runtime configuration is invalid` | Rejected before factory/hardware construction; no run or control artifact. |
| Duplicate active session | Second `runtime start` with the same active session | Exit `4` | `error: runtime session is already running` | First owner remains active and unchanged; no second run. |
| Missing session | `runtime status` and `runtime stop` for a non-running session | Exit `5` | `error: runtime session is not running` | No store or unrelated artifact is created or removed. |
| Malformed control request | Invalid JSON, missing newline, wrong fields/types, duplicate keys, or wrong protocol version sent to the private socket | Wire-level reply; harness exits `0` only if matched | Canonical JSON error code `invalid_request`, message `control request is invalid` | Owner remains active; one connection yields one reply. |
| Oversized control request | More than 8192 bytes | Wire-level reply; harness exits `0` only if matched | Same canonical `invalid_request` reply | Owner remains active; no partial request is processed. |
| Unknown control command | Strict message with unsupported command | Wire-level reply; harness exits `0` only if matched | Canonical JSON error code `unknown_command`, message `control command is unknown` | Owner remains active. |
| Unknown or invalid run ID | `runs show` or `events --run` | Exit `11` | `error: runtime run is not found` | No history mutation; stdout empty. |
| Invalid run-list limit | `runs list --limit 0`, `101`, or non-integer | Argparse exit `2` | Usage plus final error containing `limit must be between 1 and 100` | Command does not open or mutate history. |
| Invalid event cursor | `events --after -2` or non-integer | Argparse exit `2` | Usage plus final error containing `after must be an integer at or above -1` | Command does not open or mutate history. |
| Invalid event limit | `events --limit 0` or `1001` | Argparse exit `2` | Usage plus final error containing `limit must be between 1 and 1000` | Command does not open or mutate history. |
| Invalid prune keep | Missing, negative, above `9223372036854775807`, or non-integer `--keep` | Argparse exit `2` | Usage; range error when a value is supplied | No history mutation. |
| Missing history | `runs list`, unknown `show/events`, and `prune --keep 0` before store creation | Exits `0`, `11`, `11`, `0` | List/prune: empty stderr and stdout `run-count=0` / `deleted-runs=0`; show/events: empty stdout and stderr `error: runtime run is not found` | History root remains absent. |
| Unsafe history permissions | History root/file mode differs from `0700`/`0600` | Exit `10` | `error: runtime history failed` | Fail before mutation; bytes, names, and modes remain unchanged. |
| History symlink/wrong type/unknown artifact | Any task-owned fixture containing one forbidden entry | Exit `10` | `error: runtime history failed` | Fail closed with zero deletion or repair. |
| Ambiguous/unsafe control artifact | Symlink, wrong type, unsafe mode, missing required lock, or unknown session entry | Exit `6` | `error: runtime control failed` | Preserve ambiguous/unrelated entries; never use the manifest PID to signal. |
| Schema mismatch or corrupt logical store | Wrong `user_version`, object/column/index/FK drift, invalid row, event gap, or watermark mismatch | Exit `10` | `error: runtime history failed` | No partial stdout, migration, repair, deletion, or partial prune. |
| SIGINT | Deliver SIGINT after complete readiness | Owner exit `0` | Owner stderr empty; stdout ends `runtime=stopped` | Ordered cleanup; run `interrupted/sigint`, 12 contiguous events, no session directory. |
| Forced process termination | Kill after active prefix is queryable | POSIX signal result (`returncode < 0`), not a fabricated CLI code | No new product error is required after uncatchable termination | Durable run remains incomplete with prefix `0..3`; later logic may reclaim only recognized stale control artifacts and must not infer a crash result from PID. |
| Busy database or initialization lock | Controlled writer/lock holder exceeds the implemented 1 s store bound | Exit `10` for the exercised CLI history path | `error: runtime history failed` | Bounded return with rollback/no partial deletion; runtime cleanup still attempted when an owner is involved. |
| Cleanup failure | Controlled deterministic cleanup fault | Stop client and owner exit `8` when exposed through CLI | `error: runtime cleanup failed` | All available cleanup steps and later artifact cleanup are attempted; durable result is `cleanup_failed/cleanup_failure` when finalization remains possible. |

Environment-blocked classification is reserved for explicit host capability
failures such as unavailable Python 3.12, package/DNS access, unsupported
platform, unavailable Unix sockets, or an unusably long platform socket path.
A timeout in start, status, query, stop, prune, owner exit, or cleanup is an
acceptance failure, not environment-blocked. Runner-capacity failure is neither
a product failure nor passing evidence.

## H. Founder black-box acceptance

This is a founder acceptance session, not an external-human usability study.
The participant is the founder and the record must say so.

### Session setup and flow

- Target duration: 15–20 minutes; hard acceptance limit: 20 minutes.
- Provide only the installed-wheel command sheet, the wheel/config inputs, and
  a fresh task-owned environment. Do not provide implementation source or test
  names during the session.
- The founder must start the canonical simulation owner, observe readiness,
  use a second terminal/process for status and history, identify the active run
  and event prefix, stop the runtime, confirm finalized history, and observe
  cleanup.
- The founder must run one invalid session query and one unknown run query and
  identify their fixed sanitized errors.
- The founder must explain that control state is local and ephemeral, history
  is local and durable until explicit prune, and no cloud/control plane is
  required.
- The founder must explicitly avoid and reject any physical-hardware, XL430,
  release, publication, ARM64, hard-real-time, or certified-safety conclusion.

### Required measurements and pass rule

| Measurement | Pass threshold |
| --- | ---: |
| Completion time | At most 20 minutes |
| Assistance requests after the command sheet handoff | `0` |
| Blockers | `0` |
| Unexpected traceback or path/config/credential leak | `0` |
| Task-owned live process after cleanup | `0` |
| Task-owned artifact after final workspace cleanup | `0` |
| Founder decision | Explicit `ACCEPT` |

The evidence record must include the candidate SHA, wheel filename, platform
and architecture, start/end times or elapsed duration, counts above, exact
commands at a sanitized level, observed stable markers, deviations, and the
founder decision. It must not include real temporary paths, PID values, run
UUIDs, timestamps from history rows, credentials, raw configuration, or machine
identity.

## I. Platform matrix

| Platform | Required RTO-4 evidence | Acceptance boundary |
| --- | --- | --- |
| Ubuntu | Full quality gate plus the installed-wheel journey and all required RTO-4 automated markers on the candidate SHA. | Required. Exact image may follow `ubuntu-latest`, but the assigned runner/image must be recorded. |
| macOS Intel/x86_64 | Focused runtime portability tests plus the installed-wheel journey and all required RTO-4 automated markers on a GitHub-hosted `macos-15-intel` runner. | Required. Runner assignment and x86_64 evidence must be recorded. |
| ARM64 / Apple Silicon | No hosted passing evidence required or currently claimed. | Not required, not evidenced, and not a substitute for Intel evidence. |
| Physical hardware | Separate explicit-consent HCA track. | Pending and outside RTO-4. The physical test remains explicitly unselected. |

Workflow success alone is insufficient. The evidence review must verify exact
head SHA, job IDs, runner labels and assignment, OS/architecture, every critical
step conclusion, exact test counts, all required markers, and cleanup. A
cancelled/unassigned runner produces no portability evidence.

## J. Exit gates

RTO-4 may be marked complete only when all gates below are true:

- the accepted version of this contract is integrated;
- the necessary RTO-4 verifier/test slice is integrated without product-scope
  expansion;
- local acceptance passes at the exact candidate SHA;
- hosted Ubuntu acceptance passes at that SHA;
- hosted macOS Intel/x86_64 acceptance passes at that SHA;
- the founder black-box session passes;
- a sanitized founder and automated evidence record is integrated;
- `README.md`, `PRESEED.md`, the runtime architecture, and the software evidence
  index are synchronized;
- the final worktree/index is clean;
- local `HEAD`, `origin/main`, and live GitHub `main` are equal; and
- physical, ARM64, release, tag, publication, safety, and local-first boundaries
  remain correct.

Any false gate means `RTO-4 ACCEPTED: NO`. Tagging, releasing, or publishing is
neither required for RTO-4 completion nor automatically authorized by it.

## K. Accepted work-slice plan

The founder approved this work-slice plan on 2026-10-22. Slice A accepts and
freezes the contract; RTO-4 acceptance execution has not started, and Slices B,
C, and D have not started.

### RTO-4 Slice A — Acceptance Contract Freeze

- **Purpose:** review and integrate only the approved acceptance boundary.
- **Exact allowed files:**
  `docs/architecture/runtime-operations-alpha-acceptance.md` only.
- **Entry gate:** RTO-3 complete; clean synchronized `main`; founder reviews
  every Section L decision.
- **Exit gate:** all decisions are recorded in the document; links, fences,
  tables, CLI forms, exit codes, and evidence references validate; hosted docs
  gate passes after any authorized commit; the integrated contract is accepted
  and frozen with `RTO-4 ACCEPTANCE EXECUTION STARTED: NO` and
  `READY FOR RTO-4 SLICE B: YES`.
- **Dependencies:** RTO-1–RTO-3 contracts and current CI evidence.
- **Stop condition:** any mismatch with code/tests, unresolved required
  decision, or scope pressure for a runtime feature.
- **Commit/release boundary:** one docs-only commit may be separately
  authorized; no tag, release, publication, or package-version change.

### RTO-4 Slice B — Black-box Acceptance Harness

- **Purpose:** produce only the missing acceptance orchestration/evidence for
  existing behavior; add no runtime feature.
- **Exact allowed file classes:**
  `scripts/verify_clean_install.py`, its verifier tests,
  `tests/integration/test_runtime_cli.py`, narrowly relevant runtime control or
  history tests needed for deterministic fault fixtures,
  `docs/development/clean-install-and-demo.md`, and `.github/workflows/ci.yml`.
  Production files under `src/` are excluded.
- **Entry gate:** Slice A accepted and integrated; exact E2 cases and marker
  names approved.
- **Start transition:** authorized Slice B implementation changes
  `RTO-4 ACCEPTANCE EXECUTION STARTED` to `YES`.
- **Exit gate:** local automated RTO-4 matrix passes; existing RTO-3 markers
  remain valid; Ubuntu and macOS Intel jobs execute the candidate and pass with
  reviewed markers and cleanup.
- **Dependencies:** existing verifier isolation, subprocess helpers, current
  CLI, and task-owned filesystem fixtures.
- **Stop condition:** any observed product defect, need to edit `src/`, unsafe
  cleanup target, hardware interaction, unbounded wait, or ambiguous failure
  classification. A product defect becomes a separately authorized bounded fix,
  not an in-slice workaround.
- **Commit/release boundary:** one acceptance-only commit may be separately
  authorized; no product feature, tag, release, or publication.

The founder-approved default is to reuse and extend the existing
`verify_clean_install.py` orchestration because it already owns clean wheel
construction, source isolation, deadlines, process cleanup, and canonical
markers. A second verifier is not justified for the core journey. The exact
reason Slice B is still needed is that the current verifier does not exercise
installed-wheel multi-session isolation, SIGINT, forced crash/recovery, or the
full negative/fault matrix. A separate thin wrapper should be considered only
if implementation review proves that extending the existing verifier would
mix incompatible evidence lifecycles; it must reuse the existing wheel and
cleanup primitives rather than duplicate them.

### RTO-4 Slice C — Founder Acceptance Session

- **Purpose:** execute Section H and record founder-observed black-box evidence.
- **Exact allowed file classes:** one new sanitized evidence record under
  `docs/evidence/`; no code, tests, verifier, workflow, package, or existing
  status-document edits.
- **Entry gate:** Slice B integrated; exact local/Ubuntu/macOS candidate evidence
  passes; worktree clean; prepared wheel SHA equals the candidate SHA.
- **Exit gate:** all Section H thresholds pass and the founder records explicit
  `ACCEPT`.
- **Dependencies:** accepted command sheet and integrated acceptance harness.
- **Stop condition:** blocker, timeout over 20 minutes, assistance request,
  unexpected leak, leftover task-owned artifact/process, SHA mismatch, or any
  physical/release claim.
- **Commit/release boundary:** the evidence record may be committed only after
  explicit acceptance; no tag, release, publication, or physical operation.

### RTO-4 Slice D — Evidence and Closure Sync

- **Purpose:** reconcile accepted technical and founder evidence and close
  RTO-4 without changing behavior.
- **Exact allowed files:** `README.md`, `PRESEED.md`,
  `docs/architecture/runtime-operations-alpha.md`, this contract, the accepted
  RTO-4 evidence record, and the existing software evidence index.
- **Entry gate:** Slices A–C integrated and their exact hosted evidence passes.
- **Exit gate:** all Section J gates pass; status documents agree; final
  local/origin/live SHA equality and clean worktree are recorded.
- **Dependencies:** sanitized evidence with exact SHAs, jobs, counts, markers,
  platform, and founder decision.
- **Stop condition:** missing/failed/cancelled CI, unassigned macOS runner,
  evidence inconsistency, dirty scope, or an unresolved claim boundary.
- **Commit/release boundary:** one docs-only closure commit may be separately
  authorized; no automatic tag, release, publication, package-version change,
  or second corrective commit after a failed closure gate.

## L. Founder decision points

There are exactly seven independent founder-approved decisions below. The
approved defaults are frozen by the recorded decision:

| # | Decision | Approved default | Alternatives / consequence | Approval state |
| ---: | --- | --- | --- | --- |
| 1 | Acceptance-only boundary | **Yes.** No runtime feature or public contract expansion. | A feature request must become a separate bounded capability. | Approved by founder on 2026-10-22. |
| 2 | Founder black-box session | **Mandatory.** It is a distinct E3 gate. | Omitting it would make RTO-4 automated acceptance only and requires changing the stated objective. | Approved by founder on 2026-10-22. |
| 3 | Verifier strategy | **Reuse and extend `verify_clean_install.py`; avoid a second verifier by default.** | A thin wrapper is allowed only if reuse cannot preserve evidence isolation; duplication is rejected. | Approved by founder on 2026-10-22. |
| 4 | Required hosted platforms | **Ubuntu full quality and GitHub-hosted macOS 15 Intel/x86_64.** | Adding platforms expands scope and schedule; removing either weakens the current portability boundary. | Approved by founder on 2026-10-22. |
| 5 | Completion versus release | **Keep separate.** RTO-4 completion creates no tag, release, publication, or version bump. | Coupling them would turn acceptance into a release milestone and requires separate authorization. | Approved by founder on 2026-10-22. |
| 6 | ARM64 / Apple Silicon | **Out of scope and not required.** Do not claim passing evidence. | A future dedicated portability slice may add it. | Approved by founder on 2026-10-22. |
| 7 | Physical hardware | **Out of scope and separately evidenced.** Keep HCA pending. | Physical execution requires its own explicit-consent task and evidence. | Approved by founder on 2026-10-22. |

After successful Slice A integration:

```text
RTO-4 CONTRACT ACCEPTED: YES
RTO-4 ACCEPTANCE EXECUTION STARTED: NO
READY FOR RTO-4 SLICE B: YES
RTO-4 SLICE C STARTED: NO
RTO-4 SLICE D STARTED: NO
RTO-4 ACCEPTED: NO
PHYSICAL HARDWARE ACCEPTANCE: NO
```

Founder approval recorded on 2026-10-22:

```text
APPROVE RTO-4 CONTRACT DEFAULTS
```

This recorded decision is contract approval only. It is not automated
acceptance, the founder black-box session, overall RTO-4 acceptance, physical
acceptance, or release authorization.
