# Module/Driver SDK External Dry-Run Evidence

## Decision

- Gate: `HCA-SDK-5`
- Result: `PASS`
- Status: `CLOSED`
- Accepted by: Founder / product owner
- Acceptance date: `2026-10-12`
- Participant class: external human
- Anonymous participant code: `p1012`
- Codex role: execution/support tool, not the participant
- Prior HIYELX exposure: `SUBSTANTIAL`
- Prior-exposure exception: founder-approved
- Participant revision: `9e4e1f9615da75bd4be6717277e36b8cab85542b`
- Physical hardware operations: none
- Assistance requests: `0`
- Facilitator interventions: `0`
- Environment blockers: `0`

The founder reviewed the supplied FIX-2 evidence, corrected its participant
provenance, approved the prior-exposure exception, accepted the external-human
evidence, and granted founder acceptance. Earlier draft language that described
Codex as the participant is superseded by this decision: a real external human
performed the session and used Codex as an execution/support tool.

Personal identity, personal paths, credentials, tokens, environment dumps, and
raw machine-specific temporary paths are intentionally excluded.

## Environment and timing

- Operating system: macOS 27.0.1
- Architecture: arm64
- Python: 3.12.14
- uv: 0.12.7
- Checkout: fresh clone in an isolated workspace
- Start: `2026-10-12T20:00:01+03:00`
- Completion: `2026-10-12T20:22:49+03:00`
- Time to first scaffold: `00:16:49`
- Time to first generated-test pass: `00:18:39`
- Time to first clean installed import: `00:21:36`
- Total measured duration: `00:22:48`

Timing is baseline evidence only; no time-based pass/fail threshold applied.

## Accepted results

| Check | Result | Evidence |
|---|---|---|
| Fresh clone | PASS | Clone completed in an isolated workspace |
| Revision equality | PASS | Local `HEAD` and `origin/main` both matched the supplied 40-character SHA |
| Interactive shell validation | PASS | Updated SHA and participant-code blocks completed in interactive zsh without history-expansion or parser errors |
| Locked environment | PASS | Python 3.12 locked development environment installed |
| HIYELX wheel | PASS | `hiyelx-0.2.0a1-py3-none-any.whl` built and installed non-editably |
| Installed CLI | PASS | Installed `hiyelx` CLI generated the participant scaffold |
| Scaffold layout | PASS | Exact six-file layout matched |
| Generated pytest | PASS | `5 passed in 0.13s` |
| Ruff | PASS | `All checks passed!` |
| Pyright | PASS | `0 errors, 0 warnings, 0 informations` |
| External wheel | PASS | `participant_p1012_motor_driver-0.1.0-py3-none-any.whl` built and installed non-editably |
| Version contract | PASS | External package `0.1.0`; exact dependency `hiyelx==0.2.0a1` |
| Clean imports | PASS | HIYELX and participant driver resolved from `$CLEAN_ENV`, outside both source trees |
| External-driver verifier | PASS | All five required signals matched |
| Assistance/intervention/blocker count | PASS | `0 / 0 / 0` |
| Physical-operation exclusion | PASS | No hardware, serial, torque, or movement operation occurred |

## Exact scaffold evidence

```text
README.md
participant_p1012_motor_driver/__init__.py
participant_p1012_motor_driver/participant_p1012_motor_driver.py
pyproject.toml
runtime.yaml
tests/test_driver.py
```

## Clean import evidence

```text
hiyelx-import=clean path=$CLEAN_ENV/lib/python3.12/site-packages/hiyelx/__init__.py
driver-import=clean path=$CLEAN_ENV/lib/python3.12/site-packages/participant_p1012_motor_driver/__init__.py
```

## Automated verifier evidence

```text
hiyelx-wheel=hiyelx-0.2.0a1-py3-none-any.whl
external-wheel=acme_motor_driver-0.1.0-py3-none-any.whl
scaffold-tests=passed
imports=clean
external-runtime-grpc=passed
```

## Usability findings

The participant correctly identified:

- the generated vendor-specific implementation file;
- the public `Motor` lifecycle, command, and state contract;
- strict frozen driver-owned Pydantic settings;
- the explicit registration function and stable model name;
- application-owned trusted registration rather than configuration-driven code
  loading;
- the independent external package version and exact HIYELX dependency;
- the software-only evidence boundary; and
- why a physical production backend must never be supplied to the compliance
  harness.

No new P0, P1, or P2 finding was reported. The FIX-2 interactive-zsh
validation completed without `event not found`, parser errors, or shell-option
intervention.

## Reviewed artifact integrity

The sanitized source artifacts remain outside the canonical repository. Key
artifact SHA-256 digests at founder review time were:

| Artifact | SHA-256 |
|---|---|
| `observed-head.txt` | `77626991c3f24660014e7aea3d186b9c773b0e4e5e5342e96aec18592f1315c7` |
| `observed-origin-main.txt` | `77626991c3f24660014e7aea3d186b9c773b0e4e5e5342e96aec18592f1315c7` |
| `scaffold-layout.txt` | `3708d5d9cc36a954d4778364b9d79e6d9264d46b402b5cc294cafc3850f3fedc` |
| `external-driver-verifier.txt` | `e9afd0f9c0a830164ccf91e776e4b8ca5663d7c2d52428cec898311f7d79e741` |
| `generated-pytest.txt` | `3f2ea59ea3ff3b1f8ed8689f38597c7b6868acf5bbab9f1e2bf4e322510ff5ce` |
| `ruff.txt` | `82b3e6a6c090a57601d22943bd23fca9218d1031dbe5a7b754092f9a156b4f18` |
| `pyright.txt` | `6d88a1b220adb7a3d62092b6e38431f0b3fe8babe9864fab90e5849766260332` |
| `wheels.txt` | `9e803eac9c9bbf78478e67cb34d717fe9c1e64ca80ed7b1fc44c5ee1bc82a17b` |
| `clean-import.txt` | `44459129dfcb44cfa440fc11a8faecb5176fcae7b5ebdea0b043911033b3a2cd` |
| `usability-answers.md` | `0038205c5cab0944b077a83b5c22c50f89e44139f8280049b4fabc2bd79a6517` |

## Founder exception and acceptance

The participant disclosed `SUBSTANTIAL` prior HIYELX exposure. The founder
explicitly approved that exception and treated the founder decision as the
authoritative participant classification. The founder also accepted Codex as
an execution/support tool used by the external human participant.

This exception is specific to this bounded Founder Mode gate. It does not
change the underlying measured outputs, create a general eligibility rule, or
convert automated verification into human evidence by itself.

## Scope boundary

This record closes HCA-SDK-5 external usability for the documented
Module/Driver SDK Alpha local-wheel workflow. It does not close or establish:

- XL430 physical acceptance;
- real reference-driver physical acceptance;
- Physical Hardware Proof;
- physical compatibility with any motor or transport;
- emergency-stop or certified functional-safety behavior;
- hard-real-time behavior;
- broad ecosystem compatibility;
- a `v0.2.0a1` tag or release; or
- PyPI or other package-registry publication.

HCA-HW-0 is the next program gate. Runtime Operations Alpha remains after the
hardware-readiness boundary. Physical Hardware Proof remains deferred and
separately evidenced.

## Related records

- Participant runbook:
  [`../development/module-driver-sdk-external-dry-run.md`](../development/module-driver-sdk-external-dry-run.md)
- Blank reusable template:
  [`module-driver-sdk-external-dry-run-template.md`](module-driver-sdk-external-dry-run-template.md)
- SDK guide: [`../development/module-driver-sdk.md`](../development/module-driver-sdk.md)
- Software evidence index: [`software-evidence-index.md`](software-evidence-index.md)
- Delivery state: [`../../PRESEED.md`](../../PRESEED.md)
