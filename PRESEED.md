# HIYELX PRE-SEED Founder Mode

## North Star

> Change the hardware, not the application.

HIYELX must expose stable application-level resource APIs that behave the same
against deterministic simulation and real hardware. Hardware selection belongs
behind the hardware abstraction layer (HAL), not in application code.

## Working model

PRE-SEED optimizes for time-to-working-product. Work has only three states:

### NOW

**Foundation -> Resource Core**

Establish the smallest reliable Python foundation, then implement the Resource
contract: identity, lifecycle, health, and deterministic failure behavior.

Foundation exit criteria:

- The `hiyelx` package imports on Python 3.12.
- The local quality gate passes.
- CI runs the same quality gate.
- No cloud or hardware-vendor runtime dependency is introduced.

Resource Core exit criteria:

- A resource has a stable identity and explicit lifecycle states.
- Lifecycle transitions and invalid transitions are deterministic.
- Health can be inspected through a vendor-neutral contract.
- Unit tests cover the public contract and failure paths.

### NEXT

Move one bounded capability at a time through the milestone list below. The
next capability after Resource Core is Motor API plus `SimulatedMotor`.

### DONE

- Repository initialized.
- PRE-SEED product boundary, technical thesis, and canonical stack documented.
- Founder Mode workflow established.
- Minimal Python Foundation established when the quality gate passes.

## Minimum quality gate

Every change must pass locally before it is considered done:

```bash
uv run ruff check .
uv run pyright
uv run pytest
```

The CI workflow mirrors this gate. CI is intentionally small; it is a fast
verification loop, not a release-management system.

## Processes removed for PRE-SEED

The following are not mandatory while HIYELX is in Founder Mode:

- Linear issues or GitHub issues for every change
- Feature branches and pull requests for every change
- Multi-stage or release-oriented CI/CD
- Sprint ceremonies, story points, labels, and heavyweight status workflows
- ADRs for routine, reversible implementation decisions

Issues, branches, pull requests, and ADRs may still be used when they reduce
risk or clarify a consequential decision. They are tools, not gates.

## Milestones

1. **Foundation** — Python 3.12 package, uv environment, quality gate, minimal CI.
2. **Resource Core** — identity, lifecycle, health, and failure contracts.
3. **Motor API + Simulation** — vendor-neutral API and deterministic simulated motor.
4. **Configuration + Model Registry** — validated topology and pluggable model lookup.
5. **Runtime Manager** — dependency graph, ordered startup, shutdown, and ownership.
6. **gRPC Boundary** — external process commands an actuator and reads state.
7. **Real Reference Driver** — one real backend with simulation/real API parity.
8. **Reliability Baseline** — faults, timeouts, safe-stop, structured logs, and health.
9. **PRE-SEED Demo** — the same client runs unchanged against simulated and real hardware.

## Scope boundary

PRE-SEED does not include cloud/SaaS product work, Supabase integration,
general-purpose autonomy, hard real-time control in Python user space, or a
certified functional-safety claim.
