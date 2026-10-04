# Codex engineering rules

These rules apply to the entire HIYELX repository.

## Before changing code

1. Read `README.md` and `PRESEED.md`.
2. Read the documentation and tests relevant to the requested capability.
3. Confirm the requested capability's boundary and avoid unrelated work.

## Bounded scope

- Work only on the capability named in the task.
- Do not add speculative features, broad refactors, or unrequested dependencies.
- Keep public contracts small, typed, explicit, and testable.
- Prefer the smallest reversible design that satisfies the current exit criteria.

## Runtime and hardware boundaries

- Vendor-specific code must remain behind the hardware abstraction layer (HAL).
- Vendor types, SDK objects, and device assumptions must not leak into resource or
  application-level APIs.
- Simulation and real implementations must preserve application-level API parity.
- The robot runtime must remain local-first and must not require a cloud service,
  network connection, Supabase, or another control plane to operate.

## Quality and safety

- Tests are mandatory for new behavior and bug fixes, including relevant failure paths.
- Do not claim certified functional safety. Safety behavior in this repository is
  a best-effort engineering baseline unless an explicit certification program exists.
- A large, cross-cutting, difficult-to-reverse architecture change may require an
  ADR in `docs/decisions/` before implementation.
- Do not weaken type checking, lint rules, or tests to make a change pass.

## Definition of done

After every change, run:

```bash
uv run ruff check .
uv run pyright
uv run pytest
```

Report the results and any verification that could not be completed.
