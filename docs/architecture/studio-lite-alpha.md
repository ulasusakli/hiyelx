# Studio Lite Alpha Product and UX Contract

> - **Status:** Accepted / Frozen — STUDIO-P0 Product/UX Contract
> - **Founder approval:** `APPROVE STUDIO-P0 CONTRACT DEFAULTS`
> - **Approval date:** `2026-10-29`
> - **Evidence baseline:** `985e36e4072aa95056a5e1a17641a85fbd7bb6c3`
> - **Package version:** `0.2.0a1`
> - **Hosted baseline:** Quality gate `40858324158`
> - **Implementation:** Not started
> - **Physical acceptance:** Separate / Pending

This accepted contract defines the founder-approved local-first Studio Lite
product/UX defaults for observing the accepted Simulation/Preview Alpha. Founder
approval accepts and freezes these contract defaults; it is not implementation
authorization or physical acceptance evidence. Studio implementation remains
unstarted and requires separate bounded authorization.

## 1. Product outcome

Studio Lite should let a person observe an already-running local simulation
through an understandable, safe, observational interface instead of requiring
them to interpret terminal output:

> HIYELX's running local simulation runtime, observed through a clear,
> safe, read-only, local-first application experience.

The user can select an observable local session, see whether its runtime is
running, recognize that the data is simulation, and inspect ordered resource
cards. The interface explains motor position and velocity in SI units,
simulation time, revision, lifecycle, and health as separate concepts. It
shows snapshot freshness and sanitized connection/session errors. The user
does not need to read terminal JSON.

The existing public preview is a typed, canonical `SimulationPreviewSnapshot`
with schema version `1`. It contains a runtime state and ordered resources;
each supported motor resource has an application identity, kind, lifecycle,
health and sanitized health summary, angular position in radians, angular
velocity in radians per second, per-resource simulated seconds, and a revision
counter. Revision is the count of successful resource-state mutations;
preview reads do not increment it. An unchanged revision alone does not prove
that runtime state, lifecycle, health, or the whole snapshot is unchanged. In
the UI, revision is an explanatory diagnostic counter, not evidence of
physical movement, physics fidelity, or hardware state. Preview reads do not
mutate runtime or simulation state. Studio must render this model rather than
reconstruct it from status text, events, or history.

## 2. Contract status and evidence baseline

The evidence baseline for this accepted contract is commit
`985e36e4072aa95056a5e1a17641a85fbd7bb6c3`. Quality gate
[`40858324158`](https://github.com/ulasusakli/hiyelx/actions/runs/40858324158)
passed on that exact commit:

- Ubuntu job `123394864790`: `706 passed, 1 physical skipped`.
- macOS job `123394865247`: `macos-15-intel`, Intel/x86_64, `366 passed`.
- Both installed-wheel verifier runs emitted exactly 29 lines, all `8/8` SIM
  markers, and final marker `sim-preview-acceptance=passed`.

This is the accepted Simulation/Preview Alpha software baseline. STUDIO-P0 is
accepted/frozen as a product/UX contract; this does not mean implementation has
started. Package version remains `0.2.0a1`; this contract changes no tag,
release, publication, or physical acceptance state.

## 3. MVP screen

The accepted MVP default is one observational dashboard. It does not contain
runtime controls or a second operational console.

```text
┌──────────────────────────────────────────────────────────────────┐
│ HIYELX Studio Lite                         [ SIMULATION ]         │
├──────────────────────────────────────────────────────────────────┤
│ Session  [ Select local session                  ▾ ]  Connected   │
│ Snapshot freshness: updated just now                              │
├──────────────────────────────────────────────────────────────────┤
│ Runtime: Running                      Resources: 1                │
├──────────────────────────────────────────────────────────────────┤
│ sim_motor                                      motor              │
│ Lifecycle: Running       Health: Healthy                          │
│ Position: 0.0 rad        Velocity: 0.0 rad/s                      │
│ Simulation time: 0.0 s   Revision: 0                               │
│ Health summary: No known represented fault                         │
├──────────────────────────────────────────────────────────────────┤
│ Local only · Read only · Simulation values are not physical proof │
└──────────────────────────────────────────────────────────────────┘
```

This desktop-shaped wireframe is illustrative, not a fixed-width requirement.
The approved minimum supported viewport is 320 CSS pixels. At that width,
the header and session controls wrap or stack, the resource grid may become one
column, technical identities and numeric values remain readable without
clipping, and units stay attached to their values. Below the supported minimum,
show a bounded unsupported-viewport message or equivalent fallback rather than
requiring horizontal page scrolling for the primary interaction.

Minimum visible elements:

1. HIYELX Studio Lite title and persistent `SIMULATION` badge.
2. Labeled local session selector and connection state.
3. Runtime state and resource count.
4. Resource cards in preview-schema order, with identity and kind.
5. Separate lifecycle and health labels, plus optional sanitized health
   summary.
6. Position in radians, velocity in radians per second, simulation time in
   simulated seconds, and revision with concise help explaining its mutation
   count and that preview reads do not increment it.
7. Snapshot freshness or last-refreshed indication.
8. Empty, loading, unavailable, stale, unsupported-schema, disconnected, and
   sanitized-error states.
9. Persistent local-only and read-only explanation.
10. Responsive layout and a visible fallback below the supported viewport.

Health means only the software/simulation health observation represented by the
preview. It is not evidence of physical motor health, sensor health, safe
physical operation, physics fidelity, or certification.

### Screen layout and interaction

The header identifies the application and simulation boundary. A session bar
places session selection beside connection and freshness status. A compact
runtime summary precedes the ordered resource grid. Each card groups
application identity and kind, lifecycle and health, then state values with
their units. A persistent footer states that the app is local and read-only
and that simulation is not physical evidence.

The resource grid follows the `resources` array order in schema v1. Studio
must not sort by display label, vendor, or an inferred model. Identity is a
stable application-level resource name; kind is its general category.

## 4. UX state model

The following copy and behavior are approved defaults. Retry means another
bounded snapshot fetch only; it never starts, stops, commands, advances, or
reconfigures a runtime.

| State | User message | Badge / severity | Retry behavior | Hidden technical detail | Bounded user action |
|---|---|---|---|---|---|
| App starting | “Studio Lite is starting.” | Neutral / loading | Wait for host readiness; no request loop before ready. | Host startup exception, path, and process detail. | Wait or close the app. |
| No local session | “No observable local session is available.” | Neutral / empty | Refresh the local session list on explicit refresh or bounded list polling. | Session manifests, socket paths, and runtime storage. | Refresh the list or close the app. |
| Session selected / connecting | “Connecting to the selected local session…” | Neutral / connecting | One bounded snapshot request for the current selection generation; no overlapping request. | Private protocol and socket details. | Cancel selection or choose another listed session. |
| Connected / fresh snapshot | “Connected. Simulation snapshot is current.” | Informational / connected | Continue the approved single-flight polling policy. | Private host transport details. | Select another local session or pause observation. |
| Connected / unchanged snapshot | “Connected. Snapshot contents are unchanged.” | Informational / connected | Continue bounded polling; compare the full validated typed snapshot with the last successful snapshot. | Raw response and transport messages. | Continue observing or select another session. |
| Stale snapshot | “The latest snapshot could not be refreshed. Showing the last known values.” | Warning / stale | Retry snapshot fetch within the bounded policy; keep freshness age visible. | Traceback, local paths, and exception text. | Retry once or select another session. |
| Session unavailable | “This session is unavailable. Its last snapshot is not current.” | Warning / unavailable | Bounded fetch retry only; do not restart or reconnect the runtime. | Whether the process exited, private owner state, or storage paths. | Retry observation or select another session. |
| Runtime stopped | “The selected session is not running.” | Neutral / stopped | No automatic runtime restart. Refresh the local session list. | Owner cleanup and private stop details. | Select a running session or close Studio. |
| Schema unsupported | “This Studio version cannot read this preview schema.” | Error / incompatible | Do not retry the same unsupported payload automatically. | Raw fields and decoder exception. | Close Studio and use a compatible application version. |
| Sanitized application error | “Studio could not read this snapshot.” | Error / failed | At most the bounded snapshot-fetch policy; no runtime mutation. | Tracebacks, paths, config, secrets, and backend exception text. | Retry observation once or select another session. |
| Host disconnected | “The local Studio host is disconnected.” | Error / disconnected | Bounded application-fetch recovery only; do not start a runtime or expose another transport. | Host internals, port, process ID, and private protocol. | Reopen Studio or close it. |

When the selected session changes, discard the previous session's displayed
snapshot and enter connecting/loading for the new selection. Bind every request
and result to that session and its current UI request generation. A late result
from an older selection must not update cards, errors, freshness, or connection
status for the new selection.

### Polling and freshness contract

- Poll interval: one second while the selected session view is active.
- At most one snapshot request may be in flight; the next poll waits for the
  current request to finish. This single-flight rule does not by itself prevent
  a session-switch race.
- Each request uses the existing bounded preview application boundary and its
  deadline. A UI retry repeats only a snapshot fetch.
- Each selected-session change creates a monotonically increasing UI request
  generation. Every fetch is bound to the selected session ID and generation.
  On a selection change, cancel the older request where possible; otherwise
  ignore its result. A result may update UI state only while both its session ID
  and generation still match the current selection. An old response must never
  overwrite the new session's cards, error state, freshness, or connection
  badge. Do not show the previous session's snapshot while the new one loads.
- After one failed refresh, retain the last valid snapshot as stale and show
  its age. After three consecutive failed fetches, show the session unavailable
  state. A later successful fetch returns to connected/fresh.
- Determine an unchanged snapshot only by full equality between the newly
  validated canonical typed snapshot and the last successful canonical typed
  snapshot, including every meaningful typed field used by the UI render model.
  Revision alone cannot establish snapshot equality.
- Freshness and content equality are separate: a successfully fetched snapshot
  with unchanged content is still fresh. Record freshness from the successful
  fetch receipt using a monotonic local clock, or another explicitly trusted
  host observation time. Snapshot age is relative freshness, not a serialized
  wall-clock field in `SimulationPreviewSnapshot`.
- Show revision as a resource-state mutation counter for explanation only;
  preview reads do not increment it and it does not establish whole-snapshot
  equality, physical movement, or hardware evidence.
- The UI does not reconnect the runtime. Any local host recovery is limited to
  fetching the typed application boundary again.
- The approved default is to pause visual refresh in a background tab while
  keeping the last snapshot visibly stale by age; exact browser behavior remains
  a P1 implementation detail.

## 5. Local application and typed data boundary

### Approved default: local web app with Python host

Approved default: `hiyelx studio` opens a local browser experience served by a
small Python application host. The host binds only to `127.0.0.1` on an
operating-system-selected ephemeral port and serves the UI and typed read-only
capabilities from the same origin. The host consumes the existing typed
preview application boundary and reuses `SimulationPreviewSnapshot` schema v1.
The frontend receives a validated JSON projection, never a private runtime
transport.

The UI-facing capability contract, without freezing endpoint names, is:

- list and select observable local sessions;
- fetch the current schema-v1 `PreviewSnapshot` for one selected session;
- report sanitized unavailable and application-error states;
- expose host and app version; and
- expose readiness/health if needed to render startup and disconnection states.

Current CLI `runtime status` and `runtime preview` commands require a supplied
session identifier; this contract does not claim that a public session-list
command or HTTP host already exists. Session discovery is a capability to
design behind the local application boundary before implementation.

### Options and trade-offs

| Option | Disposition | Strength | Trade-off |
|---|---|---|---|
| A. Local web app + Python host | Approved default | Reuses Python application types and the installed package; same-origin UI can remain thin and read-only. | Adds a loopback host lifecycle and local web security boundary. |
| B. Tauri/Electron desktop wrapper | Alternative | Desktop packaging and native window lifecycle. | Adds a second packaging/runtime stack before the UI model is validated. |
| C. CLI text scraping | Rejected | Low initial implementation effort. | Brittle presentation parsing; loses typed schema and stable error distinctions. |
| D. Direct private socket/SQLite | Prohibited | Appears to avoid an adapter. | Couples UI to private protocol/storage and bypasses the public typed boundary. |
| E. Cloud dashboard | Deferred / out of scope | Could support remote/fleet use later. | Requires network/control-plane identity and changes the local-first MVP. |

### Boundary requirements

- Browser code consumes only the host's typed same-origin JSON surface.
- The Python host calls the typed HIYELX application boundary; it does not
  scrape `hiyelx` CLI text or reconstruct preview values from status output.
- The browser never opens the private Unix socket, reads SQLite/history, or
  parses runtime-internal files.
- No WebSocket in the first MVP. No external network, cloud, control plane,
  telemetry, or credential storage.
- The host does not add a runtime mutation capability. The UI-facing contract
  contains reads only.
- Exact route names, HTTP verbs, origin-token mechanics, and host lifecycle
  details remain for the bounded P2 implementation contract; this contract does
  not freeze their exact form.

## 6. Visual direction and accessibility

The approved visual direction is **industrial clarity, not sci-fi decoration**.
Use one high-contrast, readable theme for the MVP; dark/light theme choice is
not a launch requirement. Keep generous grouping and clear numeric hierarchy
without turning the screen into a dense engineering console.

- Keep the `SIMULATION` badge visible in every dashboard state.
- Never encode connection, lifecycle, health, or severity by color alone; pair
  color with text and a consistent icon or label.
- Use monospace only for technical identities and numeric values where it
  improves scanning.
- Keep SI units adjacent to each numeric value.
- Render lifecycle and health in separate labeled fields.
- Preserve resource ordering from the preview schema.
- Do not add decorative motion that obscures state or suggests physical motion.
- Update position, velocity, simulation time, and revision in stable positions:
  no rolling-number, count-up, or decorative transition effects; minimize
  numeric-column width changes and layout shift; do not flash/flicker the card
  or move keyboard focus when values refresh. Keep units attached to values.
- Do not send every one-second numeric update as an assertive live-region
  announcement. Announce meaningful connection and error transitions through
  a separate appropriate status message.
- At the approved 320 CSS-pixel minimum viewport, wrap/stack header and
  session controls, allow a one-column resource grid, preserve readable
  identities and numeric values without clipping, keep units attached, avoid
  horizontal page scrolling as the primary interaction, and preserve a visual
  order matching keyboard focus. Below that minimum, show the bounded fallback
  described by the wireframe. Exact CSS breakpoints remain a P1 choice.

Minimum accessibility acceptance:

- Full keyboard navigation and visible focus indicators.
- Semantic page landmarks, one clear page heading, and logical nested headings.
- A programmatic label for the session selector.
- Status text in addition to every color-coded status.
- WCAG AA contrast target for text and controls.
- Respect reduced-motion preferences; loading must not be conveyed only by
  animation.
- Keep refreshed numeric values stable without rolling/count-up animation,
  card flash, avoidable layout shift, or focus loss; do not announce each
  one-second value update to assistive technology.
- Numeric values and units must be read together by assistive technology.
- Announce meaningful errors and connection-state changes without repeatedly
  announcing every poll.

## 7. Security and privacy boundary

The MVP must:

- bind only to loopback by default; binding to external or all interfaces is
  prohibited. IPv4 and IPv6 loopback behavior must be explicit and tested;
- fail closed on unexpected Host headers and include explicit protection
  against DNS rebinding;
- require same-origin requests, reject unexpected Origin values, disable CORS
  by default, and prohibit wildcard origins;
- protect the browser-launch URL/capability so another local web page cannot
  arbitrarily call the Studio API. The exact bounded capability mechanism is a
  P2 implementation decision; do not persist credentials in browser storage
  or leak a secret URL/capability into logs or evidence;
- prevent browser or intermediary caches from reusing session-specific snapshot
  and error responses;
- reject unknown schemas and oversized requests/responses. P2 must define
  bounded request and response sizes before implementation;
- start and shut down the host within bounded deadlines and remove its owned
  process, port binding, and temporary artifacts on close. Host shutdown must
  not stop the HIYELX runtime;
- work without a cloud service, account, or control plane;
- send no telemetry and store no credentials in browser storage;
- omit raw traceback, filesystem path, config, environment, secret, process ID,
  socket path, database path, and private protocol payload from the UI;
- map failures to fixed sanitized application messages;
- fail closed on unknown schema versions or fields rather than guessing;
- expose read-only operations only; reject unsafe HTTP methods and provide no
  mutation endpoint. UI retry repeats a snapshot read only;
- keep private Unix sockets and SQLite/history storage outside the frontend
  boundary;
- expose no frontend route or capability that starts/stops a runtime, issues a
  motor command, or advances time; and
- contain no physical operation, hardware discovery, serial access, transport,
  torque, or movement path.

These are required P2 security outcomes, not frozen implementation choices.
The separately reviewed P2 host/IPC contract must make them testable before
host code is authorized. It must specify the exact bind and Host/Origin/CORS
policy, browser-launch capability protection, cache behavior, request/response
limits and rejection, fail-closed schema handling, bounded startup/shutdown,
and cleanup ownership without exposing private runtime surfaces or mutating
runtime lifecycle.

## 8. Explicitly deferred from MVP

The following are not STUDIO-P0 or Studio Lite MVP features:

- runtime start/stop;
- motor commands or position/velocity command entry;
- advance-time or other simulation-time controls;
- configuration editing;
- charts, timeline, replay, or a durable history browser;
- event explorer;
- camera;
- shared bus or 3DOF visualization;
- autonomy;
- cloud account, control plane, remote access, or telemetry;
- plugin marketplace;
- physical hardware control or torque enable/disable;
- release, tag, or package publication; and
- certified-safety or hard-real-time claims.

Some may be reconsidered as future roadmap proposals after separate contracts
and evidence. Their appearance in that roadmap would not add them to the MVP.

## 9. Implementation slices after STUDIO-P0

The founder-approved slices below set sequencing, not authorization. Each requires its
own bounded scope confirmation after STUDIO-P0 decisions are accepted.

### STUDIO-P1 — Static Application Shell

- **Scope:** App frame, dashboard layout, typed fixture data, resource-card
  components, keyboard/accessibility structure, and loading/empty/error states.
- **Allowed surfaces:** A future UI package/app, presentation components,
  static fixtures, and focused UI tests; exact paths and framework remain
  undecided.
- **Dependencies:** Accepted STUDIO-P0 product/UX contract and separate
  STUDIO-P1 authorization.
- **Exit gate:** Static screen matches the approved wireframe, renders all
  states from fixtures, satisfies accessibility checks at the supported
  minimum viewport (including wrapping, one-column cards, readable values,
  attached units, and consistent focus order), uses stable non-flashing numeric
  refresh presentation without focus loss or per-poll announcements, includes
  revision help text, and has no runtime connection.
- **Non-goals:** Live host, runtime control, private transport, or persistence.
- **Evidence:** Static UI/component and accessibility test evidence.

### STUDIO-P2 — Local Read-Only Host Adapter

- **Scope:** Local loopback host, typed schema-v1 preview access, observable
  session listing/selection, bounded polling/freshness, selected-session
  generation handling, and sanitized errors.
- **Allowed surfaces:** Separately approved host adapter, same-origin UI
  transport, host lifecycle and focused host/security tests.
- **Dependencies:** P1 static shell and a separately reviewed host/IPC,
  session-discovery, and threat-boundary contract. That contract must define
  the security outcomes below before code authorization; endpoint names,
  framework, and capability format remain open until implementation review.
- **Exit gate:** Browser receives typed snapshots and sanitized read failures;
  each request/result is bound to selected session and monotonic UI generation,
  stale-generation results are ignored, and old snapshots are cleared on
  selection change. Tests prove IPv4/IPv6 loopback-only binding, fail-closed
  Host validation and DNS-rebinding protection, same-origin/Origin validation,
  default-closed non-wildcard CORS, protected browser launch capability without
  persistent credential storage or log/evidence leakage, non-reusable caching
  for session-specific snapshot/error responses, bounded request/response size
  with oversized and unknown-schema rejection, bounded host startup/shutdown
  and owned artifact cleanup, safe-method-only read surface, and no runtime
  lifecycle mutation. No private socket/SQLite access, external bind, or
  network dependency exists; host shutdown leaves the runtime lifecycle alone.
- **Non-goals:** Runtime lifecycle control, commands, charts, history, or
  telemetry.
- **Evidence:** Local adapter contract, security tests, and read-only boundary
  tests.

### STUDIO-P3 — Live Observational Dashboard

- **Scope:** Connect the installed HIYELX application to a running installed-
  wheel simulation, render ordered resource cards and runtime/session states,
  and validate stale/disconnect/recovery UX across supported platforms.
- **Allowed surfaces:** Previously approved host/UI adapter, dashboard
  components, and cross-platform integration tests.
- **Dependencies:** P2 accepted and a separately authorized live integration
  scope.
- **Exit gate:** Exact schema-v1 state renders with stable ordering/units;
  observation does not mutate runtime state; sanitized failure states work on
  each required platform.
- **Non-goals:** Runtime start/stop, motor/time commands, physical execution,
  or physics-fidelity claims.
- **Evidence:** Installed-wheel, cross-platform UI/host integration and
  read-only regression evidence.

### STUDIO-P4 — Founder Usability and Pre-Seed Closure

- **Scope:** Bounded founder journey, clean-install path, sanitized evidence,
  packaging decision, and documentation closure for the observational product
  surface.
- **Allowed surfaces:** Separately approved evidence and closure documents,
  packaging metadata only if explicitly authorized, and the founder-journey
  harness.
- **Dependencies:** P3 integrated and hosted-tested; separate founder
  authorization for the usability session.
- **Exit gate:** Founder usability evidence and bounded technical/hosted
  evidence reviewed and integrated, with all product and physical claims kept
  distinct.
- **Non-goals:** Physical acceptance, release, tag, publication, autonomy,
  hard-real-time, or certified-safety claims.
- **Evidence:** Founder usability record, hosted quality results, and reviewed
  pre-seed closure evidence.

### Indicative effort estimate

| Milestone | Estimated focused effort |
|---|---:|
| STUDIO-P0 | 1–2 days |
| STUDIO-P1 | 3–5 days |
| STUDIO-P2 | 4–7 days |
| STUDIO-P3 | 4–7 days |
| STUDIO-P4 | 2–4 days |
| **Total** | **About 3–5 focused founder weeks** |

These are planning estimates, not delivery dates or guarantees. Dependency,
review, platform, and founder-feedback delays may change them.

## 10. STUDIO-P0 acceptance matrix

This matrix records the accepted STUDIO-P0 contract scope and its evidence/exit
criteria. Contract acceptance accepts the product/UX defaults only; it does not
authorize Studio implementation or claim Studio, physical, release, or safety
evidence.

| ID | Claim | Required evidence | Exit gate |
|---|---|---|---|
| STUDIOP0-GOAL-01 | Product outcome is a local, safe, read-only simulation observation experience. | Founder-reviewed problem statement and scope. | Simulation, local-first, and observational purpose are explicit. |
| STUDIOP0-SCOPE-01 | MVP includes one dashboard and the listed preview fields only. | MVP screen inventory and deferred list. | No deferred control/history/camera/autonomy feature enters MVP. |
| STUDIOP0-UX-01 | Session, runtime, resource, freshness, revision, and simulation meaning are understandable at supported viewports. | Wireframe, glossary/help text, responsive behavior, and message review. | Every required field has user-facing meaning; revision is explained as a successful resource-state mutation counter that reads do not increment, and the layout remains readable with attached units at the supported minimum viewport. |
| STUDIOP0-STATES-01 | Empty, loading, stale, unavailable, unsupported, error, and disconnected states are defined without cross-session races. | State/message/action matrix and session-switch generation rules. | Every state has severity, bounded fetch behavior, sanitized detail policy, and only current-session/current-generation responses can update it. |
| STUDIOP0-DATA-01 | UI consumes PreviewSnapshot schema v1 and preserves deterministic order and units. | Typed data-boundary review. | No text scraping or schema inference; units and resource order are preserved. |
| STUDIOP0-BOUNDARY-01 | A local application host separates browser UI from runtime internals and rejects stale session responses. | Typed host/IPC options, boundary diagram, and selected-session generation contract. | Frontend cannot access private socket/SQLite/internal files; only current session/generation responses update the UI; host close does not stop or mutate the runtime. |
| STUDIOP0-SECURITY-01 | Local host and UI have a bounded, testable local-only threat boundary. | P2 threat contract covering bind, Host/Origin/CORS, launch capability, cache, sizes, errors, lifecycle, and privacy. | P2 exit tests cover IPv4/IPv6 loopback-only bind, Host/DNS-rebinding and Origin/CORS rejection, launch-capability protection, non-reusable session responses, bounded payload rejection, bounded owned cleanup, safe-method-only reads, and no runtime mutation. |
| STUDIOP0-A11Y-01 | Dashboard is keyboard and assistive-technology usable across its supported viewport. | Accessibility checklist and representative screen review at minimum viewport. | Focus, labels, contrast, status text, attached units, responsive layout/fallback, stable numeric refresh, reduced motion, and meaningful error announcements are specified. |
| STUDIOP0-BRAND-01 | Visual direction is readable and consistent with HIYELX engineering clarity. | Brand-direction review and low-fidelity wireframe. | One reliable theme, visible SIMULATION label, separate lifecycle/health, no decorative sci-fi language. |
| STUDIOP0-HANDOFF-01 | P1–P4 sequencing and authorization boundaries are clear. | Slice plan, dependencies, and evidence gates. | P1 remains unstarted until separate founder approval; physical/release claims stay separate. |

## 11. Founder decisions

These ten independent decisions record the founder-approved defaults. Their
alternatives and trade-offs remain for context; none authorizes implementation
without separate bounded approval.

1. **Product shell**
   - **Approved default:** One observational dashboard with a persistent
     simulation label and local session selector.
   - **Alternative:** A multi-page operations workspace.
   - **Trade-off:** One screen keeps the MVP learnable and bounded; a larger
     workspace can organize future capabilities but expands navigation and
     scope.
   - **Approval state:** `Approved by founder on 2026-10-29.`

2. **Browser versus desktop wrapper**
   - **Approved default:** Local browser UI opened by `hiyelx studio`.
   - **Alternative:** Tauri/Electron shell.
   - **Trade-off:** Browser delivery reuses Python packaging and a same-origin
     host; a wrapper adds native lifecycle and distribution work.
   - **Approval state:** `Approved by founder on 2026-10-29.`

3. **Local host and IPC boundary**
   - **Approved default:** Python host on `127.0.0.1`, OS-selected ephemeral
     port, same-origin typed JSON, existing preview application boundary, and
     no WebSocket, with all required P2 Host/Origin/CORS, launch-capability,
     cache, payload, lifecycle, and read-only protections from Section 7.
   - **Alternative:** A desktop bridge or another separately specified local
     IPC boundary.
   - **Trade-off:** Loopback HTTP is browser-compatible but introduces host
     origin and lifecycle security requirements; desktop IPC increases
     packaging complexity.
   - **Approval state:** `Approved by founder on 2026-10-29.`

4. **Polling interval and freshness**
   - **Approved default:** One-second active-view polling, single in-flight
     request, full typed-snapshot equality for unchanged content, visible age
     based on successful observation receipt, stale after a failed refresh,
     unavailable after three consecutive failures, and monotonically increasing
      session-generation checks that discard old responses. Pause visual refresh
      in a background tab while keeping the last snapshot visibly stale by age.
   - **Alternative:** Manual refresh only or a slower interval.
   - **Trade-off:** Polling keeps the dashboard current without adding a push
     channel; it costs bounded local reads and needs clear stale behavior.
   - **Approval state:** `Approved by founder on 2026-10-29.`

5. **Session discovery and selection**
   - **Approved default:** A local host lists only observable local sessions
     and the user selects one; each selection gets a new request generation,
     clears the previous snapshot, and ignores any late response from the old
     selection; no implicit runtime start.
   - **Alternative:** Manual session-ID entry.
   - **Trade-off:** Listing is easier to use but needs a new typed discovery
     capability; manual entry avoids discovery but exposes internal session
     labels to users.
   - **Approval state:** `Approved by founder on 2026-10-29.`

6. **Visual theme**
   - **Approved default:** One high-contrast, light-neutral engineering
     theme with restrained status accents and a readable responsive layout at
     the approved 320 CSS-pixel minimum viewport.
   - **Alternative:** Dark theme or theme switching.
   - **Trade-off:** One theme keeps P1 small; theme choice can follow user
     feedback and accessibility checks.
   - **Approval state:** `Approved by founder on 2026-10-29.`

7. **MVP screen scope**
   - **Approved default:** Header, simulation badge, session/connection
     bar, runtime summary, ordered resource cards, freshness, and local/read-only
     footer, with revision help and stable non-flashing numeric refresh.
   - **Alternative:** Separate resource detail pages or event/history panels.
   - **Trade-off:** A single view explains the current snapshot without adding
     navigation or durable-history semantics.
   - **Approval state:** `Approved by founder on 2026-10-29.`

8. **Error and reconnect policy**
   - **Approved default:** Sanitized state messages; retry only typed
     snapshot fetches; stale after a failed refresh; show unavailable after
     three consecutive failures; never restart/reconnect the runtime.
   - **Alternative:** Manual-only retry or immediate unavailable state.
   - **Trade-off:** Retaining the last snapshot aids diagnosis but requires a
     prominent stale label and visible age.
   - **Approval state:** `Approved by founder on 2026-10-29.`

9. **Accessibility baseline**
   - **Approved default:** Keyboard-first navigation, visible focus,
     semantic structure, WCAG AA contrast target, non-color status, reduced
     motion, readable units, announced errors, responsive focus order, and no
     per-poll live-region announcements for changing numeric values.
   - **Alternative:** None for these minimums; implementation details may be
     staged if an equivalent accessible result is demonstrated.
   - **Trade-off:** Accessibility is part of the screen contract; it may shape
     component and status-announcement design from P1 onward.
   - **Approval state:** `Approved by founder on 2026-10-29.`

10. **STUDIO-P1 implementation authorization**
    - **Approved default:** P1 begins only after this contract is accepted
      and the founder separately authorizes the bounded static-shell slice.
    - **Alternative:** Keep implementation blocked until a new product
      milestone review.
    - **Trade-off:** Separate authorization prevents an accepted contract from
      becoming implied implementation permission.
    - **Approval state:** `Approved by founder on 2026-10-29.`

## 12. Accepted MVP outcome and boundaries

If the later slices pass their separate review and acceptance gates, the Studio
Lite MVP is intended to provide:

- a working local-first application experience;
- observation of an installed HIYELX simulation session;
- a session/runtime/resource dashboard;
- position, velocity, simulated time, and revision with clear units/meaning;
- read-only refresh over an unchanged snapshot;
- sanitized error states;
- a cross-platform tested host/UI path;
- founder usability evidence; and
- a pre-seed demo-ready observational product surface.

That future outcome does not include physical motor control, autonomy,
production release, physics-fidelity proof, hard-real-time behavior, or
certified safety. Physical hardware acceptance remains a separate pending
evidence track.

## 13. Relationship to accepted contracts

This accepted contract does not change other accepted contracts or evidence:

- [Simulation/Preview Alpha and schema v1](simulation-preview-alpha.md)
- [SIM-P2 Local Preview Adapter](simulation-preview-local-adapter.md)
- [SIM-P3 Founder Acceptance and Studio handoff](simulation-preview-founder-acceptance.md)
- [Runtime Operations Alpha](runtime-operations-alpha.md)
- [Software Evidence Index](../evidence/software-evidence-index.md)
- [HIYELX PRE-SEED Founder Mode](../../PRESEED.md)
- [README and current product state](../../README.md)
- [PRE-SEED Master Plan v3.0](../plans/HIYELX_PRESEED_Master_Plan_v3.0.docx)

The repository currently contains no frontend package or existing Studio UI.
The only matching product-plan document found is the PRE-SEED Master Plan;
dedicated Studio design-system or web-app UI/UX guideline documents were not
present. The plan prioritizes a local working product, a readable technical
story, and explicit separation of software and physical proof. This contract's
visual direction is the founder-approved lightweight product direction, not a
claim that a separate Studio design system already exists.

## 14. Founder approval record and implementation boundary

Founder decision: `APPROVE STUDIO-P0 CONTRACT DEFAULTS` on `2026-10-29`. This
approval accepts and freezes the STUDIO-P0 product/UX defaults recorded above.
It does not authorize or start Studio implementation: no UI, frontend, or local
host code has been created, STUDIO-P1 has not started, and STUDIO-P1 requires a
separate bounded authorization. The STUDIO-P1 handoff is contractually defined,
but this approval does not grant that separate authorization. This contract
approval is not commit or push authority, physical hardware acceptance, release,
tag, or publication approval.
