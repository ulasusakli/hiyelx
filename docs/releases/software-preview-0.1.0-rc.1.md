# HIYELX Software Preview 0.1.0-rc.1 Candidate

## Historical candidate status

This document is the evidence pack for **SPRC-1: Software Preview Release
Candidate**. It describes a candidate for a bounded Software Developer Preview;
it is not a release announcement or evidence that a preview was published.

- Candidate version: `0.1.0-rc.1`
- Package version under evaluation: `0.1.0`
- Candidate preparation baseline: `1b08de10a2ab2484cf7fa0bf35cb0cc41cff6945`
- Repository: `https://github.com/ulasusakli/hiyelx`
- Evidence index: [`../evidence/software-evidence-index.md`](../evidence/software-evidence-index.md)
- Candidate-time release status: **NOT RELEASED** (historical)

No Git tag, GitHub Release, package publication, version bump, or physical
hardware acceptance is created by this candidate.

## Subsequent release outcome

The founder subsequently accepted this pack for a bounded software-only
release. The resulting
[`v0.1.0` GitHub release](https://github.com/ulasusakli/hiyelx/releases/tag/v0.1.0)
uses package version `0.1.0` and targets commit
`e3801ed43ec4b173dae765ac583055314defce50`. It is a pre-release and is not a
draft. No package was published to PyPI or another registry, and no binaries
were attached to the GitHub release. Physical acceptance remained deferred.

The `0.1.0-rc.1` label remains the identity of this historical evidence-pack
revision; it was not the package version or final Git tag. HCA-SDK-1 through
HCA-SDK-4 were added later on `main` and are not included in the `v0.1.0`
release snapshot.

## Supported software workflow

The supported preview workflow is local, software-only, and requires Python
3.12, uv 0.12 or newer, Git, IPv4 loopback, and access to the locked Python
dependencies (from an index or an already populated cache).

It validates the canonical configuration and demonstrates the existing
configuration to registry to `RuntimeManager` to loopback gRPC to `Motor`
contract with `SimulatedMotor`. Simulation time advances explicitly; the
workflow performs no serial discovery, hardware access, or physical movement.

```bash
git clone https://github.com/ulasusakli/hiyelx.git
cd hiyelx
uv sync --locked --dev
uv run hiyelx validate-config examples/configs/sim-motor.yaml
uv run hiyelx demo sim-motor
uv run python scripts/verify_clean_install.py
```

The exact 14-line demo transcript is
[`../../examples/expected/sim-motor.txt`](../../examples/expected/sim-motor.txt).
The clean-install verifier builds a wheel, installs it non-editably in a fresh
Python 3.12 environment outside the checkout, rejects source-checkout imports,
and reruns the validation and demo path.

## Candidate quality gates

The SPRC-1 candidate worktree was verified on 2026-10-08:

| Gate | Candidate result |
|---|---|
| `uv lock --check` | PASS; 23 packages resolved |
| `uv run python scripts/generate_proto.py --check` | PASS; committed generated modules are consistent |
| `uv run ruff check .` | PASS; all checks passed |
| `uv run pyright` | PASS; 0 errors, 0 warnings in configured strict mode |
| `uv run pytest` | PASS; 244 passed, 1 physical test skipped, 0 failed, 0 deselected |
| `uv build --wheel` | PASS; built `hiyelx-0.1.0-py3-none-any.whl` |
| Wheel license inspection | PASS; `License-Expression: Apache-2.0`, `License-File: LICENSE`, canonical bytes matched |
| `uv run python scripts/verify_clean_install.py` | PASS; license checks and clean install reported `clean-install=passed` |

Environment-blocked tests: 0. The physical test was not run because it requires
explicit hardware opt-ins and `-m hardware`. These local results are software
evidence, not package publication or physical acceptance.

## Public API and packaging status

- The Python distribution is `hiyelx`, version `0.1.0`, requiring Python 3.12
  or newer.
- The installable `hiyelx` command exposes `validate-config` and
  `demo sim-motor`.
- Public typed contracts are exported by the Resource, Motor, configuration,
  model registry, Runtime Manager, and gRPC packages.
- `proto/hiyelx/v1/motor.proto` remains the versioned RPC source of truth;
  generated Python modules and typing stubs are committed and checked for
  consistency.
- The wheel contains the canonical SIM configuration and is verified through a
  non-editable clean installation.
- Repository and package licensing use the founder-authorized Apache License
  2.0. Distribution metadata declares `Apache-2.0`, and the wheel gate verifies
  the embedded canonical `LICENSE` file.
- There is no compatibility promise beyond the explicitly documented PRE-SEED
  contracts, and there is no package-registry publication in SPRC-1.

## Evidence classes

The candidate keeps three kinds of evidence separate:

1. **Software implementation evidence** consists of tracked source,
   architecture documents, deterministic tests, packaging checks, and local CI
   gates listed in the [software evidence index](../evidence/software-evidence-index.md).
2. **External developer evidence** is the founder-accepted EDR-1 record at
   [`../evidence/2026-10-08-external-developer-dry-run.md`](../evidence/2026-10-08-external-developer-dry-run.md).
   Its recorded limitations remain part of that evidence and it makes no claim
   about broad developer usability.
3. **Physical hardware evidence** has not been produced. The real XL430 driver
   implementation has software tests, but Real Reference Driver physical
   acceptance and Physical Hardware Proof remain deferred.

## Security and safety boundaries

- The runtime is local-first and has no required cloud service, telemetry,
  remote logger, database, authentication service, or control plane.
- gRPC is unauthenticated and unencrypted and accepts only literal IPv4
  loopback binding. It is not approved for remote or Internet-facing use.
- Configuration does not dynamically import arbitrary modules; registration is
  explicit and instance-local.
- Client-facing failures and local structured events use sanitized,
  vendor-neutral summaries rather than raw backend exceptions, credentials,
  device paths, or arbitrary device data.
- RB-1 deadlines and RB-2 safe-stop are best-effort software reliability
  mechanisms. They are not an emergency stop, hard-real-time guarantee,
  hardware watchdog, or certified functional-safety system.
- Physical operation requires an independent hardware procedure, secured test
  setup, and accessible physical power cutoff. None is authorized by this RC.

## Known limitations and deferred capabilities

- Physical XL430 acceptance and the full Real Reference Driver milestone are
  incomplete.
- At candidate time, the Software Developer Preview had not yet been released;
  the subsequent bounded release outcome is recorded above.
- Authentication, authorization, TLS, and remote binding are not implemented.
- Retries, reconnect, recovery loops, watchdogs, heartbeats, background
  polling, and shared DYNAMIXEL bus management are deferred.
- Fleet telemetry, remote logging, metrics exporters, cloud runtime
  dependencies, and a web UI are absent.
- The packaging gate covers one supported Python version, not a platform
  matrix, installer suite, release pipeline, signing system, or publication
  workflow.
- No hard-real-time or certified functional-safety claim is made.

## Licensing and release blockers

The founder selected Apache License 2.0. LIC-1 implements that decision with
the unmodified canonical text in the repository-root [`LICENSE`](../../LICENSE),
the PEP 639 package expression `Apache-2.0`, and deterministic wheel checks for
both metadata and license-file inclusion.

The distributed first-party and generated files were inspected for retained
attribution requirements. Runtime dependencies are declared rather than
vendored, and no distributed third-party NOTICE content was found. A `NOTICE`
file is therefore not required for this bounded integration; no copyright owner
or speculative attribution was invented.

The missing-license blocker was closed. At candidate time, release still
required separate founder review and authorization; that authorization and the
bounded GitHub pre-release subsequently occurred as recorded above.

Physical hardware acceptance is not a prerequisite for evaluating this
software-only candidate, but it remains required for the Real Reference Driver,
Physical Hardware Proof, and full PRE-SEED milestone.
