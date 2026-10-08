# External Developer Dry-Run Evidence

## Decision

- Result: `PASS`
- Accepted by: Founder / product owner
- Acceptance date: 2026-10-08
- Participant code: `EDR-001`
- Starting revision: `32e47a023cbf0313ffcce0be295ce81b3ef380ba`
- Physical hardware operations: none
- Environment-blocked steps: none

The founder witnessed the fresh-clone workflow and explicitly accepted this
session as closing the External Developer Dry Run gate. Personal participant
identity is intentionally not stored.

## Environment

- Operating system: macOS; exact version was not recorded
- Architecture: Apple Silicon / arm64
- Python: 3.12.14
- uv: 0.12.7
- Checkout: fresh clone in a separate test directory
- Prior HIYELX use by the host or user: not recorded

## Observed procedure

The witnessed session executed the documented runbook sequence:

1. Clone `https://github.com/ulasusakli/hiyelx.git` into a fresh directory.
2. Confirm local `HEAD` and `origin/main` at the intended revision.
3. Record Python and uv versions.
4. Install the locked development environment.
5. Validate `examples/configs/sim-motor.yaml`.
6. Run `hiyelx demo sim-motor` and capture its output.
7. Compare the captured output with the canonical 14-line transcript.
8. Run the isolated non-editable wheel verifier.

All required commands completed successfully. No facilitator intervention or
assistance request was reported in the supplied terminal transcript.

## Results

| Check | Result | Evidence |
|---|---|---|
| Fresh clone | PASS | Clone completed from live GitHub repository |
| Intended revision | PASS | Local `HEAD` and `origin/main` both matched the starting revision |
| Locked installation | PASS | 23 packages resolved; development environment installed |
| Configuration validation | PASS | `configuration=valid` |
| Deterministic SIM demo | PASS | Complete 14-line transcript produced |
| Transcript comparison | PASS | `cmp` completed without a difference |
| Non-editable wheel installation | PASS | `clean-install=passed` |
| Installed wheel | PASS | `hiyelx-0.1.0-py3-none-any.whl` |
| Physical hardware exclusion | PASS | No serial, torque, motion, or hardware test was used |

## Canonical transcript

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

## Artifact integrity

The raw files remain outside the canonical repository. Their SHA-256 digests at
review time were:

| Artifact | SHA-256 |
|---|---|
| `starting-commit.txt` | `23a1ae72b8e5102fb93ede5a7fca5ae8340f927e1f034ef364925315c29b3859` |
| `sim-motor.actual.txt` | `d26298cf80dd22b0ada83667257e3ca5d9dad4deb9e1276e12e7c50e43ffb7f6` |
| `clean-install.actual.txt` | `18bd8d781d5fbdbc7444e803fe1a0a761c32165ec2de739dba4484f7f4b60243` |

## Findings

- P0: none reported
- P1: none reported
- P2: none reported
- Environment-blocked: none

## Accepted evidence limitations

- Exact macOS version was not captured.
- Start time and time-to-first-SIM were not captured, so this session does not
  establish a time benchmark.
- Host-level prior HIYELX use and participant independence were not separately
  recorded beyond the founder's witnessed acceptance.

The founder explicitly accepted these evidence gaps for the PRE-SEED Founder
Mode gate. They do not convert into claims about broader developer usability.

## Scope boundary

This record closes only the External Developer Dry Run gate. It does not close
the Real Reference Driver physical acceptance, Physical Hardware Proof, or the
full PRE-SEED milestone.
