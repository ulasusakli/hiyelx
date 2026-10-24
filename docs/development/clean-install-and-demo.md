# Clean Installed-Wheel and Runtime Acceptance Evidence

The clean-install gate proves that a built HIYELX wheel runs the deterministic
simulation demo, the complete local RTO-3 run/event-history journey, and the
RTO-4 E2 automated acceptance matrix without an editable install or a
source-checkout import.

## Requirements

- Python 3.12
- uv 0.12 or newer
- macOS or Linux with local Unix-domain sockets
- IPv4 loopback binding on `127.0.0.1`
- package-index access, or a populated uv cache, for declared dependencies

No serial enumeration, hardware discovery, transport opening, actuator, motor
power, torque, movement, cloud service, credential, or remote listener is used.

## Authoritative automated journey

From the repository root, run:

```bash
uv sync --locked --dev
uv lock --check
uv run python scripts/verify_clean_install.py
```

The verifier performs all of the following in task-owned temporary roots:

1. builds a fresh wheel;
2. creates a clean Python 3.12 virtual environment;
3. installs the wheel and declared dependencies non-editably;
4. rejects checkout imports and requires `hiyelx` to resolve below the clean
   environment's `site-packages`;
5. validates the canonical simulation configuration and 14-line demo;
6. proves missing history queries and prune do not create a store;
7. starts an installed foreground owner and queries status, the incomplete run,
   and its committed startup-event prefix from separate installed CLI
   processes;
8. stops and finalizes the run, then validates terminal events and watermark;
9. starts and finalizes a second session against the same durable history;
10. validates text/JSON equivalence, cursor and limit behavior;
11. starts two additional foreground owners concurrently against the same
    history root;
12. explicitly prunes the older finalized run with `--keep 1` while preserving
    both active runs and their committed event prefixes;
13. stops each concurrent owner independently, proving that the other remains
    responsive and that both runs finalize exactly once;
14. sends SIGINT to a ready installed owner, then verifies ordered cleanup,
    `interrupted/sigint` history, and the exact `0..11` event sequence;
15. force-kills a separate ready owner, proves its committed `0..3` prefix
    remains incomplete, safely reclaims the recognized stale session with a
    new run, and stops the recovery owner normally;
16. runs the installed CLI negative matrix for invalid configuration, model,
    session, run, cursor, limit, duplicate, and missing-session cases with
    exact exit codes and sanitized output;
17. sends malformed, incomplete, duplicate-key, wrong-version, oversized, and
    unknown-command requests directly to a ready owner's private socket, then
    proves that the owner and its committed event prefix are unchanged;
18. exercises task-owned control and history fault fixtures, including unsafe
    paths, schema and logical drift, a cross-process busy SQLite writer, and a
    bounded initialization lock, without repair or partial mutation;
19. uses the installed Python and unchanged wheel code for one deterministic
    cleanup-failure harness, proving exit `8`, fixed stderr, final cleanup
    retry, and `cleanup_failed/cleanup_failure` history; and
20. centrally scans all captured product output and removes every task-owned
    process, socket, session, database, WAL, SHM,
    lock, initialization file, virtual environment, build output, and external
    driver scaffold.

The existing RTO-3 success output remains the exact prefix:

```text
wheel=hiyelx-0.2.0a1-py3-none-any.whl
history-missing-store=passed
history-active-query=passed
history-post-stop-query=passed
history-cross-process-persistence=passed
history-events-cursor-json=passed
history-prune=passed
history-artifact-cleanup=passed
clean-install=passed
```

A successful local verifier run currently appends these markers in
accepted-registry order:

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

The B1 extension reuses the same verifier, the same single wheel build, the
same clean non-editable environment, and the same task-owned durable history
root. It proves wheel/source isolation, the existing events journey, two
concurrent sessions, active-run-safe explicit prune, independent stop,
exactly-once finalization, and both control-session cleanups. It does not build
a second wheel or create a second verifier or virtual environment.

Every existing and RTO-4 marker is printed by `main()` only after the complete
journey and final temporary-root cleanup succeed. A partial failure prints no
success marker. A successful local verifier run produces local evidence only.
The presence of the code or markers in a repository does not by itself
establish integration or hosted acceptance. Integrated evidence must identify
the exact commit SHA. Hosted Ubuntu and GitHub-hosted macOS Intel/x86_64
evidence exists only when the required jobs pass against that exact SHA.

The six-marker B1 subset (`wheel-built`, `source-isolation`, `env`, `events`,
`prune`, and `multi`) was hosted-accepted at
`48ee77b5c07229ff9dba5921a46ab35da207129f`; adding local interrupt and crash
evidence or the remaining negative, sanitization, cleanup, and aggregate
evidence does not retroactively broaden that hosted result. The complete
12-marker output is local candidate evidence until separately integrated and
run on an exact hosted SHA. The final
`rto4-automated-acceptance=passed` marker means only that the E2 automated
matrix completed in that verifier run; it does not establish hosted automated
acceptance, founder black-box acceptance, overall RTO-4 acceptance, physical
acceptance, release authorization, a tag, or package publication.

## Manual clean-wheel setup

The following shell-safe setup keeps the environment, build, control state,
history, HOME, and temporary files isolated. Run it from the repository root:

```bash
TEMP_BASE="$(python3 -c 'from pathlib import Path; import tempfile; print(Path(tempfile.gettempdir()).resolve())')"
case "$TEMP_BASE" in /*) ;; *) printf '%s\n' 'error: unsafe temporary base' >&2; return 1 2>/dev/null || exit 1 ;; esac
HIYELX_REPOSITORY_ROOT="$(python3 -c 'from pathlib import Path; print(Path.cwd().resolve())')"
ORIGINAL_HOME="$HOME"
ORIGINAL_HOME_CANONICAL="$(python3 -c 'from pathlib import Path; import os; print(Path(os.environ["HOME"]).resolve())')"
ORIGINAL_TMPDIR="${TMPDIR-}"
WORK_DIR="$(mktemp -d "$TEMP_BASE/hiyelx-rto3-manual.XXXXXX")"
mkdir -m 700 "$WORK_DIR/home" "$WORK_DIR/temp"
uv build --wheel --out-dir "$WORK_DIR/dist"
uv venv --python 3.12 --no-project "$WORK_DIR/venv"
WHEEL="$(find "$WORK_DIR/dist" -maxdepth 1 -type f -name 'hiyelx-*.whl' -print -quit)"
uv pip install --strict --python "$WORK_DIR/venv/bin/python" "$WHEEL"
HIYELX="$WORK_DIR/venv/bin/hiyelx"
CONFIG="$(pwd)/examples/configs/sim-motor.yaml"
export HOME="$WORK_DIR/home"
export TMPDIR="$WORK_DIR/temp"
export HIYELX_RUNTIME_STATE_DIR="$WORK_DIR/control"
export HIYELX_RUNTIME_HISTORY_DIR="$WORK_DIR/history"
printf 'WORK_DIR=%s\n' "$WORK_DIR"
```

Keep `WORK_DIR` private. When using two terminals, copy the printed `WORK_DIR`
value into the second terminal, reconstruct the five variables above, and do
not use a real user history directory.

## Missing-store checks

Before starting an owner, these commands must not create the history root:

```bash
"$HIYELX" runtime runs list
"$HIYELX" runtime runs show 00000000-0000-4000-8000-000000000000
"$HIYELX" runtime events --run 00000000-0000-4000-8000-000000000000
"$HIYELX" runtime runs prune --keep 0
if test -e "$HIYELX_RUNTIME_HISTORY_DIR"; then false; fi
```

`runs list` prints `run-count=0`. The two unknown-run commands return exit 11
with `error: runtime run is not found`. Prune prints `deleted-runs=0`.

## Start, readiness, and active history

In terminal A:

```bash
"$HIYELX" runtime start "$CONFIG" --session wheel-one
```

Readiness is exactly:

```text
session=wheel-one
runtime=running
control=ready
```

In terminal B, using the same isolated variables:

```bash
"$HIYELX" runtime status --session wheel-one
"$HIYELX" runtime runs list
"$HIYELX" runtime runs list --json
```

Copy the run ID from the list. While the owner is active:

```bash
"$HIYELX" runtime runs show RUN_ID
"$HIYELX" runtime events --run RUN_ID
"$HIYELX" runtime events --run RUN_ID --limit 1
"$HIYELX" runtime events --run RUN_ID --json
```

The run is incomplete, its event sequence begins at zero and is contiguous,
and the output contains only fixed HIYELX summaries.

## Stop and post-stop history

From terminal B:

```bash
"$HIYELX" runtime stop --session wheel-one
"$HIYELX" runtime runs show RUN_ID --json
"$HIYELX" runtime events --run RUN_ID --after 3
"$HIYELX" runtime events --run RUN_ID --limit 1000 --json
```

Terminal A exits after ordered safe-stop and shutdown. The run becomes
`completed` with `cli_stop`; its terminal event sequence and high-water mark
match exactly. Repeat start/stop with a different session, such as `wheel-two`,
to prove both finalized runs survive separate installed CLI processes.

With two finalized runs, explicit retention is:

```bash
"$HIYELX" runtime runs prune --keep 1
"$HIYELX" runtime runs list
```

Prune prints `deleted-runs=1`. The newest finalized run and its events remain;
the removed run returns the fixed run-not-found result for both `runs show` and
`events`. Prune does not promise immediate SQLite file-size reduction because
it does not run `VACUUM`.

The B1 verifier additionally runs this prune while two more owners are active.
Both incomplete runs, their `0..3` event prefixes, and the newest finalized run
remain queryable; only the oldest finalized run is deleted. The owners remain
responsive, are stopped one at a time, and finish with exact `0..11` event
sequences without one session affecting the other.

The lifecycle extension uses two additional short, task-owned sessions. SIGINT
is sent only after readiness and the active run/event prefix are verified; the
owner must exit `0`, finalize exactly once as `interrupted/sigint`, record
events `0..11`, and remove its session directory. The forced-crash owner is
killed only after the same active-prefix checks and must exit with a negative
POSIX signal return code. Its run remains unchanged and incomplete with null
end/result/reason fields, watermark `3`, and events `0..3`. Starting the same
session safely reclaims only recognized stale control state, creates a distinct
run ID, leaves the old run unchanged, and completes the recovery run through a
normal CLI stop. These checks do not infer a crash result from a PID or return
code and do not authorize broad or ambiguous artifact cleanup.

The negative and fault extension uses only task-owned fixtures. Public CLI
cases require byte-exact stdout/stderr and a real `3.0` second subprocess
timeout; the build and install commands retain their separate 180-second
timeout. Private protocol
probes use one connection and one canonical reply each, and a disconnect never
requests stop. Unsafe control and history artifacts, including a `0700` root
with either a `0644` database or `0644` lock, schema drift, logical corruption,
busy writer contention, and initialization-lock contention must fail closed
without fixture mutation, migration, repair, retry/reconnect, or `VACUUM`.
A separate installed-Python fault harness changes no wheel file, adds no
product hook, and retains the real cleanup orchestrator. It injects a sanitized
`safe_stop` failure below that orchestrator, records that real `shutdown` is
still called next, preserves the session-artifact failure/final-retry path, and
injects a secondary event-persistence failure without changing cleanup-failure
precedence. Both stop client and owner must exit `8`, and the durable result
must be `cleanup_failed/cleanup_failure`. The central output scan covers
captured CLI output, owner output, and wire replies and rejects traceback,
absolute task paths, raw configuration or payloads, credentials, backend or
SQLite text, device/transport identifiers, PID values, and memory addresses.

## Cleanup

Stop an active owner before removing task-owned files:

```bash
"$HIYELX" runtime stop --session wheel-one
cleanup_hiyelx_rto3_manual() {
  cleanup_target="${WORK_DIR-}"
  cleanup_parent=""
  cleanup_name="${cleanup_target##*/}"
  case "$TEMP_BASE" in
    /*) ;;
    *) printf '%s\n' 'error: refusing unsafe RTO-3 cleanup' >&2; return 1 ;;
  esac
  case "$cleanup_target" in
    "$TEMP_BASE"/hiyelx-rto3-manual.*) ;;
    *) printf '%s\n' 'error: refusing unsafe RTO-3 cleanup' >&2; return 1 ;;
  esac
  if test -z "$cleanup_target" ||
     test "$cleanup_target" = / ||
     test "$cleanup_target" = "$TEMP_BASE" ||
     test "$cleanup_target" = "${HOME-}" ||
     test "$cleanup_target" = "$ORIGINAL_HOME_CANONICAL" ||
     test "$cleanup_target" = "$HIYELX_REPOSITORY_ROOT" ||
     test -L "$cleanup_target" ||
     test ! -d "$cleanup_target"; then
    printf '%s\n' 'error: refusing unsafe RTO-3 cleanup' >&2
    return 1
  fi
  cleanup_parent="$(python3 -c 'from pathlib import Path; import sys; print(Path(sys.argv[1]).parent.resolve())' "$cleanup_target" 2>/dev/null)" || {
    printf '%s\n' 'error: refusing unsafe RTO-3 cleanup' >&2
    return 1
  }
  case "$cleanup_name" in
    hiyelx-rto3-manual.*) ;;
    *) printf '%s\n' 'error: refusing unsafe RTO-3 cleanup' >&2; return 1 ;;
  esac
  if test "$cleanup_parent" != "$TEMP_BASE"; then
    printf '%s\n' 'error: refusing unsafe RTO-3 cleanup' >&2
    return 1
  fi
  rm -rf -- "$cleanup_target"
}
cleanup_status=0
cleanup_hiyelx_rto3_manual || cleanup_status=$?
export HOME="$ORIGINAL_HOME"
if test -n "$ORIGINAL_TMPDIR"; then export TMPDIR="$ORIGINAL_TMPDIR"; else unset TMPDIR; fi
unset ORIGINAL_HOME ORIGINAL_HOME_CANONICAL ORIGINAL_TMPDIR
unset WORK_DIR WHEEL HIYELX CONFIG HIYELX_REPOSITORY_ROOT
unset HIYELX_RUNTIME_STATE_DIR HIYELX_RUNTIME_HISTORY_DIR
if test "$cleanup_status" -ne 0; then unset cleanup_status; false; else unset cleanup_status; fi
```

Use the stop command only when the session is active; a completed manual
journey may proceed directly to removal of its private `WORK_DIR`. Never point
`WORK_DIR` at a repository, home directory, shared directory, or physical
device location.

## Troubleshooting boundaries

- `blocked: clean-install verification requires package access and loopback support`
  is reserved for an explicit host capability failure such as unavailable
  Python 3.12, DNS/package access, an unsupported platform, or unavailable
  local Unix-socket support.
- `error: clean-install verification failed` means packaging, isolation,
  lifecycle, history, query, prune, cleanup, or any ambiguous/product timeout
  did not match the contract.
- `error: clean-install verification interrupted` is the fixed Ctrl-C result;
  task-owned cleanup still runs and no partial success marker is emitted.
- `error: runtime run is not found` is the fixed expected result for an unknown
  or explicitly pruned run.
- `error: runtime history failed` means the store is unsafe, corrupt,
  incompatible, inaccessible, or busy beyond the bounded writer timeout.

Do not weaken ownership, symlink, permission, schema, timeout, or sanitization
checks to work around these errors. The verifier intentionally omits raw paths,
SQLite messages, payloads, and exception text.

## Evidence boundary

This is software packaging, local process-control, persistence, portability,
and cleanup evidence. It is not a release pipeline, remote deployment,
hard-real-time guarantee, certified-safety claim, or Physical Hardware Proof.
Physical acceptance requires the separate explicit consent and hardware
runbook; this workflow must never enumerate or open hardware.
