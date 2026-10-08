# External Developer Dry Run

## Status

This document is the self-contained participant runbook for EDR-1. Receiving
this runbook and the repository URL must be sufficient; no verbal setup help is
part of the measured attempt. Preparation or internal rehearsal is not external
user evidence and does not close this gate.

## Purpose and scope

Evaluate whether a developer outside the implementation loop can independently
follow the documented HIYELX installation, configuration-validation, and
deterministic simulated-motor workflow. The exercise measures documentation and
packaging usability only. It does not evaluate robotics expertise, performance,
remote deployment, or physical hardware.

Repository: `https://github.com/ulasusakli/hiyelx.git`

## Supported environment

- A fresh macOS or Linux machine, VM, user account, or genuinely isolated
  environment that has not used the prepared HIYELX checkout
- Git
- Python 3.12
- uv 0.12 or newer
- IPv4 loopback binding on `127.0.0.1`
- Package-index access, or a populated uv cache, for locked dependencies

Do not use an existing prepared HIYELX checkout. Do not connect a serial device,
power an actuator, enable torque, or run any physical hardware test.

## Participant procedure

Start the measured timer immediately before the clone command. Run commands
exactly as written, from a normal terminal, without verbal guidance.

### 1. Fresh clone and revision record

```bash
git clone https://github.com/ulasusakli/hiyelx.git
cd hiyelx
git rev-parse HEAD | tee starting-commit.txt
git rev-parse origin/main
```

Record both SHAs in the evidence template. They must match the intended GitHub
revision supplied for the session. Do not continue on an unintended revision.

### 2. Record prerequisites

```bash
python3.12 --version
uv --version
```

### 3. Install the locked development environment

```bash
uv sync --locked --dev
```

### 4. Validate the canonical configuration

```bash
uv run hiyelx validate-config examples/configs/sim-motor.yaml
```

Expected output and exit status:

```text
configuration=valid
```

Exit status: `0`.

### 5. Run and compare the deterministic SIM demo

```bash
uv run hiyelx demo sim-motor | tee sim-motor.actual.txt
cmp examples/expected/sim-motor.txt sim-motor.actual.txt
```

The demo must produce exactly these 14 lines:

```text
demo=sim-motor
configuration=valid
runtime=running
grpc=running
motors=sim_motor
command=positive velocity=2.000
advance=1.250
state=positive position=2.500 velocity=2.000
command=negative velocity=-1.000
advance=0.500
state=negative position=2.000 velocity=-1.000
command=zero velocity=0.000
stop velocity=0.000
cleanup grpc=stopped runtime=stopped
```

Both commands must exit `0`. Stop the measured timer only after `cmp` confirms
the transcript matches. Record time-to-first-successful-SIM, but do not apply a
pass/fail time threshold until external baseline evidence exists.

### 6. Verify the built wheel in a clean environment

```bash
uv run python scripts/verify_clean_install.py | tee clean-install.actual.txt
```

Expected output and exit status:

```text
wheel=hiyelx-0.1.0-py3-none-any.whl
clean-install=passed
```

Exit status: `0`. This command builds the wheel outside the checkout, creates a
fresh Python 3.12 environment, installs non-editably, rejects source-checkout
imports, reruns validation and the demo, and removes temporary files.

## Troubleshooting boundary

- Work independently from the written instructions during the measured attempt.
- If blocked, record the exact command, exit status, and sanitized output before
  asking for help.
- Package-index, DNS, Python acquisition, permission, platform, or loopback
  restrictions are `ENVIRONMENT-BLOCKED`; they are never a pass.
- Do not modify product networking, bind remotely, disable isolation checks, or
  weaken transcript comparison to accommodate a restricted environment.
- Do not silently repair this runbook or another document during the session.
  Record the ambiguity and any intervention in the evidence template.
- Never include credentials, environment-variable dumps, personal information,
  serial-device paths, or unnecessary machine-specific paths in submitted
  evidence.

## Evidence submission

Copy
`docs/evidence/external-developer-dry-run-template.md` to a separate evidence
file and complete its blank fields. Submit that completed file together with:

- `starting-commit.txt`
- `sim-motor.actual.txt`
- `clean-install.actual.txt`

Sanitize outputs before submission. Use only an anonymous participant code; do
not provide a name or email address. Record every assistance request and every
facilitator intervention.

## Facilitator protocol

1. Use a fresh machine, VM, user account, or genuinely isolated environment.
2. Do not use the existing prepared HIYELX checkout.
3. Give the participant only the repository URL and this runbook.
4. Do not provide verbal guidance during the measured attempt.
5. Record every intervention, including its timing and content category.
6. Stop the measured timer only after the deterministic transcript matches.
7. Do not silently repair documentation during the session.
8. Classify package-index, DNS, Python, platform, permission, or loopback
   restrictions as `ENVIRONMENT-BLOCKED`, never `PASS`.
9. Never modify product networking to accommodate a restricted environment.
10. Perform no physical hardware operation.

## Decision gate

`PASS` requires every condition below:

- Fresh clone completed.
- Recorded commit matches the intended GitHub revision.
- Installation completed using the documented commands.
- `validate-config` exited `0` with `configuration=valid`.
- `demo sim-motor` exited `0`.
- The canonical 14-line transcript matched exactly.
- The clean-install verifier confirmed the installed package did not resolve
  from the source checkout.
- No undocumented facilitator intervention was required.
- No P0 or P1 documentation issue remained.

Use `FAIL` when the environment was suitable but any required condition failed.
Use `ENVIRONMENT-BLOCKED` only for an external restriction that prevents a fair
execution. Record time-to-first-SIM in every attempted session, but do not add a
time-based pass/fail threshold before the first external baseline exists.

Physical acceptance remains deferred. This dry run cannot complete the Real
Reference Driver or PRE-SEED Demo physical gate.
