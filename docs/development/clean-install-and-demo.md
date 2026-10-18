# Clean Install and SIM Demo Evidence

DR-1 proves that the built HIYELX wheel can run the deterministic simulated
motor workflow without importing the source checkout or relying on an editable
installation.

## Requirements

- Python 3.12
- uv 0.12 or newer
- IPv4 loopback binding on `127.0.0.1`
- Package-index access, or an already populated uv cache, for wheel dependencies

No serial device, actuator, motor power, hardware discovery, cloud service, or
remote network listener is used.

## Locked development setup

From the repository root:

```bash
uv sync --locked --dev
uv lock --check
```

The normal developer commands remain:

```bash
uv run hiyelx validate-config examples/configs/sim-motor.yaml
uv run hiyelx demo sim-motor
```

## Wheel and clean-install gate

Build the wheel directly when inspecting packaging output:

```bash
uv build --wheel
```

Run the canonical isolated evidence gate with:

```bash
uv run python scripts/verify_clean_install.py
```

The verifier builds into a temporary directory outside the repository, creates
a fresh Python 3.12 virtual environment, installs the wheel non-editably, and
runs every child process from that external directory. It removes `PYTHONPATH`,
disables user-site imports, confirms `hiyelx` resolves inside the temporary
environment, copies and validates the canonical configuration, then executes
the loopback SIM demo. It also starts the installed wheel's simulation runtime
as a foreground subprocess, obtains the canonical status from a second
installed CLI process, requests stop from a third, requires successful owner
exit, and confirms that the private session artifacts disappeared. Temporary
build, environment, process, socket, and session files are removed after both
success and failure.

Successful evidence is concise:

```text
wheel=hiyelx-0.2.0a1-py3-none-any.whl
clean-install=passed
```

## Canonical expected transcript

The source of truth for the exact 14-line demo output is
`examples/expected/sim-motor.txt`. Both CLI regression tests and the isolated
wheel verifier load that file. The verifier compares bytes exactly, allowing
only one optional final line-feed difference.

## Troubleshooting boundaries

- `blocked: ...` means the environment prevented Python acquisition, package
  installation, IPv4 loopback binding, or local Unix-domain socket execution.
  Restore the required host capability and rerun; do not weaken the verifier or
  production transport boundary.
- `error: clean-install verification failed` means packaging, import isolation,
  command exit status, configuration validation, or transcript evidence did not
  match the contract. Run the normal quality gate and inspect locally without
  publishing temporary paths or raw environment contents.
- Wheels, build directories, virtual environments, caches, and local evidence
  outputs are temporary and must not be committed.

## Known limitations

This is one Python 3.12, software-only packaging smoke gate. It is not a release
pipeline, platform matrix, remote deployment, performance test, hardware test,
hard-real-time guarantee, or certified functional-safety claim. The demo gRPC
server remains unauthenticated and restricted to literal IPv4 loopback. The
RTO-2 control socket remains local to the current host and user. Physical XL430
acceptance and the Real Reference Driver milestone remain deferred.
