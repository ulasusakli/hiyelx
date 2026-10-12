# Module/Driver SDK External Human Dry Run

## Status and purpose

This is the self-contained participant runbook for HCA-SDK-5. It evaluates
whether an external developer can independently use the Module/Driver SDK Alpha
from a fresh clone through clean installed wheels. It is an external
human-usability test, not a physical-hardware test.

Preparation, an internal rehearsal, or execution by Codex is not external human
evidence and cannot close HCA-SDK-5. The participant receives only:

- repository URL `https://github.com/ulasusakli/hiyelx.git`;
- the intended commit SHA supplied by the facilitator; and
- this runbook.

The measured attempt allows no verbal setup assistance. Record every assistance
request and facilitator intervention. Do not connect or inspect hardware, open a
serial device, enable torque, issue movement, or run a physical test.

## Supported environment

- A fresh macOS or Linux machine, VM, user account, or genuinely isolated
  workspace
- Git
- Python 3.12
- uv 0.12 or newer
- Package-index access, or a sufficient local uv cache, for locked dependencies
- IPv4 loopback support for the automated Runtime Manager/gRPC verifier

Package-index, DNS, Python acquisition, permission, platform, or loopback
restrictions are `ENVIRONMENT-BLOCKED`, never `PASS`. Do not change product
networking or weaken isolation checks to accommodate a restricted environment.

## Facilitator protocol

1. Supply the intended 40-character commit SHA separately before the attempt.
2. Give the participant only the repository URL and this runbook.
3. Require a fresh clone and workspace; do not use a prepared HIYELX checkout.
4. Provide no verbal setup guidance during the measured attempt.
5. Record every assistance request and intervention, including its stage and
   outcome.
6. Do not silently repair documentation during the session.
7. Stop the measured timer only after all clean installed-package checks and
   the automated external-driver verifier succeed.
8. Treat a genuine external restriction as `ENVIRONMENT-BLOCKED`, never as a
   pass.
9. Perform no physical hardware operation.

## Participant procedure

Start the measured timer immediately before the first `git clone` command. Run
the commands from a normal shell. When prompted, enter the exact SHA supplied by
the facilitator and an anonymous lowercase alphanumeric participant code, such
as `p17`. Do not enter a name or email address.

### 1. Create an isolated workspace and clone

```bash
DRY_RUN_ROOT="$(mktemp -d "${TMPDIR:-/tmp}/hiyelx-sdk-dry-run.XXXXXX")"
export DRY_RUN_ROOT
cd "$DRY_RUN_ROOT"
git clone https://github.com/ulasusakli/hiyelx.git
HIYELX_SOURCE="$DRY_RUN_ROOT/hiyelx"
export HIYELX_SOURCE
cd "$HIYELX_SOURCE"
printf 'Intended commit SHA supplied by facilitator: '
IFS= read -r INTENDED_SHA
export INTENDED_SHA
if test "$(printf '%s' "$INTENDED_SHA" | LC_ALL=C wc -l | tr -d '[:space:]')" -eq 0 &&
  printf '%s\n' "$INTENDED_SHA" |
    LC_ALL=C grep -Eq '^[0-9a-f]{40}$'
then
  :
else
  printf 'error: intended SHA must be 40 lowercase hexadecimal characters\n' >&2
  false
fi
```

If the validation block returns nonzero, stop and record the failure.

```bash
git rev-parse HEAD | tee "$DRY_RUN_ROOT/observed-head.txt"
git rev-parse origin/main | tee "$DRY_RUN_ROOT/observed-origin-main.txt"
test "$(git rev-parse HEAD)" = "$INTENDED_SHA"
test "$(git rev-parse origin/main)" = "$INTENDED_SHA"
```

If either `test` command returns nonzero, stop and record the mismatch. Do not
silently switch revisions.

### 2. Record prerequisites and install the locked environment

```bash
python3.12 --version
uv --version
uv sync --locked --dev
```

### 3. Define a unique participant driver identity

```bash
printf 'Anonymous lowercase alphanumeric participant code: '
IFS= read -r PARTICIPANT_CODE
if test "$(printf '%s' "$PARTICIPANT_CODE" | LC_ALL=C wc -l | tr -d '[:space:]')" -eq 0 &&
  printf '%s\n' "$PARTICIPANT_CODE" |
    LC_ALL=C grep -Eq '^[a-z0-9]+$'
then
  :
else
  printf 'error: use one or more lowercase letters and digits only\n' >&2
  false
fi
```

If the validation block returns nonzero, stop and record the failure before
continuing.

```bash
PACKAGE_NAME="participant_${PARTICIPANT_CODE}_motor_driver"
MODEL_NAME="motor.participant.${PARTICIPANT_CODE}"
DRIVER_SOURCE="$DRY_RUN_ROOT/participant-driver"
CLEAN_ENV="$DRY_RUN_ROOT/clean-venv"
export PARTICIPANT_CODE PACKAGE_NAME MODEL_NAME DRIVER_SOURCE CLEAN_ENV
printf 'package=%s\nmodel=%s\n' "$PACKAGE_NAME" "$MODEL_NAME"
```

This avoids reusing the repository's `acme_motor_driver` verification identity.

### 4. Build and install HIYELX non-editably

```bash
mkdir "$DRY_RUN_ROOT/wheels"
uv build --wheel --out-dir "$DRY_RUN_ROOT/wheels" "$HIYELX_SOURCE"
test -f "$DRY_RUN_ROOT/wheels/hiyelx-0.2.0a1-py3-none-any.whl"
uv venv --python 3.12 --no-project "$CLEAN_ENV"
CLEAN_PYTHON="$CLEAN_ENV/bin/python"
CLEAN_HIYELX="$CLEAN_ENV/bin/hiyelx"
export CLEAN_PYTHON CLEAN_HIYELX
uv pip install --strict --python "$CLEAN_PYTHON" \
  "$DRY_RUN_ROOT/wheels/hiyelx-0.2.0a1-py3-none-any.whl"
uv pip install --strict --python "$CLEAN_PYTHON" \
  pytest==9.1.1 pytest-asyncio==1.4.0 ruff==0.16.10 pyright==1.1.414
"$CLEAN_HIYELX" --help
```

The alpha path uses an explicitly supplied local HIYELX wheel. It does not
require a Git tag or package-registry publication.

### 5. Generate and verify the exact scaffold

```bash
cd "$DRY_RUN_ROOT"
"$CLEAN_HIYELX" scaffold motor-driver "$DRIVER_SOURCE" \
  --package-name "$PACKAGE_NAME" \
  --model-name "$MODEL_NAME"
find "$DRIVER_SOURCE" -type f | \
  sed "s#^$DRIVER_SOURCE/##" | LC_ALL=C sort | \
  tee "$DRY_RUN_ROOT/scaffold-layout.txt"
printf '%s\n' \
  README.md \
  "$PACKAGE_NAME/__init__.py" \
  "$PACKAGE_NAME/$PACKAGE_NAME.py" \
  pyproject.toml \
  runtime.yaml \
  tests/test_driver.py | LC_ALL=C sort > "$DRY_RUN_ROOT/expected-layout.txt"
cmp "$DRY_RUN_ROOT/expected-layout.txt" "$DRY_RUN_ROOT/scaffold-layout.txt"
```

The exact six files are:

```text
README.md
pyproject.toml
runtime.yaml
<participant package>/__init__.py
<participant package>/<participant package>.py
tests/test_driver.py
```

Here, `<participant package>` describes the value printed as `package=...`;
do not type the angle-bracket text as a command.

### 6. Run generated software checks

```bash
cd "$DRIVER_SOURCE"
"$CLEAN_PYTHON" -m pytest -q
"$CLEAN_ENV/bin/ruff" check .
"$CLEAN_ENV/bin/pyright" --pythonpath "$CLEAN_PYTHON"
```

Expected results are five passing tests, Ruff success, and zero Pyright errors
or warnings.

### 7. Inspect the generated contract

```bash
grep -nE 'class .*Settings|def register_|MODEL_NAME|^[[:space:]]*model:|version =|hiyelx==' \
  "$DRIVER_SOURCE/$PACKAGE_NAME/$PACKAGE_NAME.py" \
  "$DRIVER_SOURCE/$PACKAGE_NAME/__init__.py" \
  "$DRIVER_SOURCE/pyproject.toml" \
  "$DRIVER_SOURCE/runtime.yaml"
```

Record, in your own words:

- which file contains the vendor-specific implementation;
- which public `Motor` contract must be implemented;
- how strict driver-owned settings are defined;
- the registration function and stable model name;
- why registration is explicit and application-owned;
- why the YAML model name does not import Python code;
- the generated external package version and exact HIYELX dependency;
- which evidence is software-only; and
- why the compliance harness must never receive a physical production backend.

### 8. Build and install the participant driver wheel

```bash
uv build --wheel --out-dir "$DRY_RUN_ROOT/wheels" "$DRIVER_SOURCE"
EXTERNAL_WHEEL="$DRY_RUN_ROOT/wheels/${PACKAGE_NAME}-0.1.0-py3-none-any.whl"
export EXTERNAL_WHEEL
test -f "$EXTERNAL_WHEEL"
uv pip install --strict --python "$CLEAN_PYTHON" --no-index "$EXTERNAL_WHEEL"
printf 'hiyelx-wheel=%s\nexternal-wheel=%s\n' \
  hiyelx-0.2.0a1-py3-none-any.whl \
  "${PACKAGE_NAME}-0.1.0-py3-none-any.whl"
```

The external driver owns its independent `0.1.0` version. It depends exactly
on `hiyelx==0.2.0a1`; the two version identities are not coupled.

### 9. Confirm clean installed imports outside both source trees

```bash
mkdir "$DRY_RUN_ROOT/application"
cd "$DRY_RUN_ROOT/application"
"$CLEAN_PYTHON" -c 'import importlib, os; from pathlib import Path; import hiyelx; env=Path(os.environ["CLEAN_ENV"]).resolve(); forbidden=(Path(os.environ["HIYELX_SOURCE"]).resolve(),Path(os.environ["DRIVER_SOURCE"]).resolve()); modules=(("hiyelx",hiyelx),("driver",importlib.import_module(os.environ["PACKAGE_NAME"]))); paths=tuple((label,Path(module.__file__).resolve()) for label,module in modules); assert all(env in path.parents and all(not (path == root or root in path.parents) for root in forbidden) for _,path in paths); [print(f"{label}-import=clean path=$CLEAN_ENV/{path.relative_to(env)}") for label,path in paths]'
```

Both lines must say `import=clean` and show paths rooted at the symbolic
`$CLEAN_ENV`, not a source checkout. Record the sanitized output.

### 10. Run the separate automated confirmation

```bash
cd "$HIYELX_SOURCE"
VERIFIER_OUTPUT="$DRY_RUN_ROOT/external-driver-verifier.txt"
export VERIFIER_OUTPUT
(
  uv run python scripts/verify_external_driver_install.py \
    >"$VERIFIER_OUTPUT" 2>&1
  VERIFIER_STATUS=$?
  cat "$VERIFIER_OUTPUT"
  test "$VERIFIER_STATUS" -eq 0 || exit "$VERIFIER_STATUS"
  grep -Fx 'hiyelx-wheel=hiyelx-0.2.0a1-py3-none-any.whl' "$VERIFIER_OUTPUT"
  grep -Fx 'external-wheel=acme_motor_driver-0.1.0-py3-none-any.whl' "$VERIFIER_OUTPUT"
  grep -Fx 'scaffold-tests=passed' "$VERIFIER_OUTPUT"
  grep -Fx 'imports=clean' "$VERIFIER_OUTPUT"
  grep -Fx 'external-runtime-grpc=passed' "$VERIFIER_OUTPUT"
)
```

Expected success signals are:

```text
hiyelx-wheel=hiyelx-0.2.0a1-py3-none-any.whl
external-wheel=acme_motor_driver-0.1.0-py3-none-any.whl
scaffold-tests=passed
imports=clean
external-runtime-grpc=passed
```

If the command block returns nonzero, stop and record its exit status and
sanitized captured output before requesting assistance.

Stop the measured timer only after this command and all preceding clean
installed-package checks succeed. Record completion time, failures, ambiguity,
assistance, interventions, and sanitized outputs in the evidence template.

## Troubleshooting and evidence boundary

- Work independently from these written instructions during the measured
  attempt.
- Before requesting help, record the command, exit status, and sanitized output.
- Do not expose credentials, environment variables, personal paths, serial
  paths, or arbitrary machine data.
- Do not use editable installation, source-tree imports, package discovery, or
  configuration-driven Python loading.
- Do not silently change the runbook, generated package, or verification rules.
- Passing is software and usability evidence only. It is not compatibility,
  physical acceptance, emergency-stop, hard-real-time, or certified-safety
  evidence.

Submit a completed copy of
[`../evidence/module-driver-sdk-external-dry-run-template.md`](../evidence/module-driver-sdk-external-dry-run-template.md)
plus the sanitized text artifacts created above. Remove the isolated workspace
only after evidence has been safely submitted.

## Decision gate

`PASS` requires all of the following:

- A fresh clone at the facilitator-supplied intended revision.
- The clean installed HIYELX CLI generated the scaffold.
- Exactly the six documented files were generated.
- All five generated tests, Ruff, and Pyright passed.
- The external wheel built successfully.
- The external package remained version `0.1.0`.
- Its dependency was exactly `hiyelx==0.2.0a1`.
- HIYELX and the participant driver imported outside both source trees.
- The automated external-driver verifier passed.
- The participant correctly identified settings, registration, model,
  independent versions, explicit-loading, and software-only boundaries.
- No undocumented facilitator intervention occurred.
- No unresolved P0 or P1 finding remained.
- No physical operation occurred.

Use `FAIL` when a supported environment was suitable but a required condition
failed. Use `ENVIRONMENT-BLOCKED` only for a genuine external restriction and
never count it as a pass. Record timing as baseline evidence; the first session
has no time-based pass/fail threshold.
