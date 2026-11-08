# Studio Lite — STUDIO-P2 Secure Local Read-Only Host Contract

> - **Status:** Frozen — STUDIO-P2.1 contract
> - **Issue:** `#2`
> - **Approval date:** `2026-11-07`
> - **Evidence baseline:** `9998b993e1665e096337e8fb76b4e6c884374483`
> - **Package version:** `0.2.0a1`
> - **Prerequisites:** STUDIO-P0 and STUDIO-P1 accepted
> - **Implementation status:** Not started
> - **Authorization:** Documentation only; P2.2 through P2.4 remain unauthorized

Normative **must** and **must not** statements freeze the P2 implementation
boundary. This document refines the accepted
[`Studio Lite Alpha`](studio-lite-alpha.md) contract without repeating its
product, visual, or accessibility requirements. Studio Lite Alpha governs the
product and UX; this document governs the P2 application, session-discovery,
HTTP, browser-transport, security, and acceptance boundaries.

## 1. Scope and trust boundary

P2 adds one local, read-only observation path:

```text
DOM-independent browser controller
    -> protected same-origin JSON over 127.0.0.1
Python Studio host
    -> typed Studio application adapter
existing typed preview request
    -> private current-user runtime control socket
```

The browser must never access or reproduce the private runtime protocol,
session manifests, socket paths, SQLite/history storage, PIDs, configuration,
environment, or filesystem paths. The host must not scrape CLI output. The
adapter may call the existing typed preview boundary and a new typed,
non-mutating session-discovery function only.

P2 contains no runtime start/stop, motor or time command, retry that mutates
runtime state, physical hardware path, external bind, external network call,
cloud service, telemetry, credential store, WebSocket, or persistence.

## 2. Typed Studio application adapter

The adapter exposes exactly two asynchronous read capabilities:

```text
list_sessions() -> tuple[str, ...]
get_preview(session: str) -> SimulationPreviewSnapshot
```

`list_sessions` returns validated observable session IDs in ascending
lexicographic order. `get_preview` validates the session ID and returns the
existing immutable schema-v1 `SimulationPreviewSnapshot`; it must not convert
CLI text or expose a raw mapping. Neither operation caches a selection or
snapshot, creates a session, reconnects a runtime, or changes runtime state.

Implementation exceptions must be mapped to typed Studio failures before the
HTTP boundary. Exception text and backend detail must never become response
content.

## 3. Non-mutating session discovery

Discovery operates only in the existing current-user runtime state root. An
absent root produces an empty session list without creating it. An observable
session is a valid session-ID directory owned by the current user with the
required private modes, a held owner lock, an exact valid manifest, and a
safely published local control socket.

Discovery must:

- inspect at most 128 root entries and return at most 64 sessions;
- validate paths without following symlinks;
- omit a structurally valid but unlocked stale session;
- treat a filesystem race, unsafe entry, unexpected artifact, invalid
  ownership/mode, malformed manifest, or exceeded bound as one sanitized
  discovery failure rather than return a partial list; and
- close every descriptor it opens.

One bounded exception permits discovery and the PREVIEW read-only locator to
temporarily acquire the validated session's advisory lock solely to determine
whether it is currently held. The probe must use a nonblocking acquisition and
must immediately release any lock it acquires. Descriptor cleanup must ensure
that no probe lock remains held after success or failure. The probe must never
establish persistent session ownership, construct an owned Runtime session, or
authorize cleanup. Ambiguous acquisition or release failures fail closed. This
exception applies only to the existing discovery/PREVIEW liveness check.

The probe has a transient kernel-level lock side effect and can briefly contend
with concurrent Runtime startup or shutdown; it is not a passive filesystem
read. A change in ownership across the bounded checks is a race and fails
closed. Studio must never reclaim a stale session, rename a directory, remove
or modify an artifact, invoke runtime cleanup, or perform a Runtime lifecycle
operation. Transient failure is recovered only by a later independent read.

## 4. Host and HTTP contract

The host uses a strict bounded HTTP/1.1 subset over an IPv4 listener created
with `AF_INET`, address `127.0.0.1`, and port `0`. It must never bind `0.0.0.0`,
an external address, `::`, or `::1`. Tests must prove the assigned IPv4
listener works and that IPv6 and non-loopback connections do not reach it.

The host accepts one request per connection, emits `Connection: close`, and
does not support upgrade, keep-alive, proxy, streaming, or chunked requests.
Only `GET` and `HEAD` are allowed on the explicitly allowlisted routes. `HEAD`
uses the same Host, Origin, capability, schema, and security checks as `GET`,
but returns no response body. Every other method, including `OPTIONS`, `POST`,
`PUT`, `PATCH`, `DELETE`, `CONNECT`, and `TRACE`, returns `405` with
`Allow: GET, HEAD`.

### 4.1 Exact routes

These initial-document and static-asset routes require no Studio capability
header, but still require the Host and Origin checks in Section 6:

| Route | Response |
|---|---|
| `/` | accepted P1 `index.html` bytes |
| `/studio.css` | accepted P1 stylesheet bytes |
| `/fixtures.js` | accepted P1 fixture bytes |
| `/app.js` | accepted P1 application-shell bytes |
| `/host-client.js` | P2 DOM-independent controller bytes |

These API routes require the capability from Section 5:

| Route | Response |
|---|---|
| `/api/v1/meta` | host/app version and readiness |
| `/api/v1/sessions` | observable local sessions |
| `/api/v1/sessions/{session}/preview` | schema-v1 preview snapshot |

Routes are ASCII and exact. Query strings, percent-encoded path components,
empty or repeated path separators, dot segments, directory listing, and every
unlisted route are rejected. A session path component must pass the existing
session-ID validator before application access.

### 4.2 Exact success schemas

`/api/v1/meta` has this exact key set:

```json
{"app_version":"0.2.0a1","host_version":"1","ready":true,"schema_version":"1"}
```

`/api/v1/sessions` has this exact key set and a sorted, duplicate-free array:

```json
{"schema_version":"1","sessions":["alpha"]}
```

The preview route returns the existing canonical schema-v1 preview JSON object
without a session or HTTP envelope. Successful JSON is UTF-8, compact,
finite-number-only, and uses sorted object keys. Unknown versions, missing or
extra fields, duplicate keys, and wrong primitive types fail closed.

### 4.3 Exact error schema

Every host-produced error uses exactly:

```json
{"error":{"code":"preview_unavailable","message":"Studio preview is temporarily unavailable."},"schema_version":"1"}
```

Only the following status/code/message triples are allowed:

| Status | Code | Message |
|---:|---|---|
| 400 | `invalid_request` | `Studio request is invalid.` |
| 403 | `request_rejected` | `Studio request was rejected.` |
| 404 | `not_found` | `Studio resource was not found.` |
| 404 | `session_not_running` | `The selected session is not running.` |
| 405 | `method_not_allowed` | `Studio request method is not allowed.` |
| 413 | `request_too_large` | `Studio request is too large.` |
| 421 | `host_rejected` | `Studio request was rejected.` |
| 422 | `preview_unsupported` | `This Studio version cannot read this preview schema.` |
| 500 | `application_error` | `Studio could not read this snapshot.` |
| 503 | `sessions_unavailable` | `Studio could not list local sessions.` |
| 503 | `preview_unavailable` | `Studio preview is temporarily unavailable.` |

Unknown routes use `not_found`. Missing or invalid capability and unexpected
Origin use `request_rejected`. An invalid or oversized application response is
rejected before any partial response and maps to `application_error`. Network
failure has no HTTP body and maps in the controller to the accepted host-
disconnected state.

## 5. Fragment-to-memory capability

Each host process creates one independent capability with at least 256 bits of
cryptographic randomness. Its launch URL is:

```text
http://127.0.0.1:<port>/#capability=<base64url-token>
```

The URL fragment is not sent in HTTP requests. Initial HTML, stylesheet, and
script loading must therefore succeed without a custom capability header. On
controller initialization, browser code must read the fragment once, validate
its exact form, immediately remove it from the visible URL and current history
entry with `history.replaceState`, and retain the token only in a private
in-memory closure.

Every `/api/v1/` request must send the exact token in
`X-HIYELX-Studio-Capability`. The host compares it in constant time before
application access. Missing, duplicated, malformed, or incorrect values fail
closed. Static routes neither require nor inspect this header.

The capability must never enter a query, path, cookie, local/session storage,
IndexedDB, service worker, serialized state, response, exception, access log,
test evidence, or referrer. All responses use `Referrer-Policy: no-referrer`.
The host must not log raw request headers or URLs. Closing the host invalidates
the capability.

This mechanism protects against unrelated web origins and DNS rebinding. It is
not a security boundary against a compromised browser, OS, or malicious
process already running as the same local user.

## 6. Host, Origin, CORS, cache, and headers

HTTP/1.1 requests must contain exactly one `Host` header equal to
`127.0.0.1:<assigned-port>`. `localhost`, alternate numeric spellings, another
port, IPv6, suffixes, user info, and forwarded-host forms are rejected with
`421` before routing. `Forwarded` and every `X-Forwarded-*` header are rejected.

An absent `Origin` is allowed for direct navigation and same-origin GETs that
omit it. If present, exactly one Origin must equal
`http://127.0.0.1:<assigned-port>`; `null`, another scheme/host/port, multiple
values, and malformed values return `403`. The host emits no
`Access-Control-Allow-*` header and does not implement CORS preflight.

Every response, including static assets and errors, includes:

```text
Cache-Control: no-store, max-age=0
Content-Security-Policy: default-src 'self'; base-uri 'none'; connect-src 'self'; form-action 'none'; frame-ancestors 'none'; img-src 'self'; object-src 'none'; script-src 'self'; style-src 'self'
Cross-Origin-Opener-Policy: same-origin
Cross-Origin-Resource-Policy: same-origin
Permissions-Policy: camera=(), geolocation=(), microphone=(), serial=(), usb=()
Referrer-Policy: no-referrer
X-Content-Type-Options: nosniff
X-Frame-Options: DENY
```

Responses include exact `Content-Type` and `Content-Length` values and must not
emit a `Server` header. Static MIME types are allowlisted; content sniffing and
filesystem-derived MIME selection are prohibited.

## 7. Bounds and lifecycle

The host enforces these exact limits before parsing or sending content:

- request line: 2,048 bytes;
- individual header line: 4,096 bytes;
- complete request head: 16,384 bytes;
- header fields: 64;
- request body: zero bytes; any transfer encoding or non-zero content length
  is invalid;
- JSON API response: 32,768 bytes; and
- individual static response: 65,536 bytes.

The request head must arrive within three seconds. The existing preview
application call retains its three-second total deadline; the enclosing HTTP
handler has a four-second deadline. Host startup and shutdown each have a
three-second deadline.

Startup becomes ready only after the listener is bound and the capability is
available. Shutdown first stops accepting connections, then cancels or awaits
owned handlers, closes the listener, drops the capability, and removes only
temporary artifacts created by that host instance. The P2 host should create
no filesystem artifact. Browser closure does not stop the runtime, and host
shutdown must never invoke runtime stop or session cleanup.

## 8. Browser transport and polling

The P2 browser controller is a DOM-independent module with injected fetch,
monotonic clock, timers, visibility source, and state callback. It performs no
rendering and does not alter the accepted P1 assets. It uses same-origin URLs,
`credentials: "omit"`, `cache: "no-store"`, `referrerPolicy: "no-referrer"`,
and the capability header for API reads. It must not use cookies, browser
storage, WebSocket, EventSource, service workers, or external URLs.

The controller validates exact response schemas before state publication. It
must reject unknown fields or versions rather than adapt them.

For a selected session it must:

- poll every one second only while the document is visible;
- allow at most one in-flight preview fetch and schedule the next only after
  the current fetch completes;
- increment a monotonic generation on every selection action;
- clear the prior snapshot immediately on selection change;
- bind every fetch and result to both session ID and generation;
- abort an obsolete request where possible and unconditionally ignore its
  late success or failure;
- record freshness from successful receipt using the monotonic clock;
- compare the complete validated typed snapshot, not revision alone;
- retain the last valid snapshot as stale after one transient refresh failure,
  show unavailable after three consecutive transient failures, and recover on
  a later success; and
- pause requests while hidden, continue computing displayed age from the last
  successful receipt, and fetch immediately when visible again.

When no valid snapshot exists, a typed session, schema, application, or network
failure maps directly to the corresponding accepted Studio Lite state; data
from another session must never be used as a stale fallback. No polling or
retry may start, stop, reconnect, command, or advance a runtime.

## 9. Required implementation evidence

P2 implementation must add focused evidence for:

- adapter success and every sanitized error mapping;
- absent-root, active, stale, unsafe, oversized, racing, and deterministic
  session discovery, including before/after proof of zero artifact mutation;
- exact IPv4 bind and explicit IPv6/non-loopback refusal;
- static GET without capability and API rejection without capability;
- capability consumption/removal, constant-time validation, and absence from
  storage, logs, referrers, responses, and evidence;
- exact Host, Origin, forwarded-header, CORS, route, method, traversal, MIME,
  cache, security-header, request-limit, response-limit, and timeout behavior;
- exact success/error schemas and fail-closed unknown schema/field handling;
- bounded startup, concurrent request shutdown, listener cleanup, and proof
  that the runtime remains active after host closure;
- single-flight polling, monotonic freshness, background pause/resume, full
  equality, first/third failure transitions, recovery, generation rollover,
  cancellation, and late-result rejection; and
- regressions proving no runtime mutation route, CLI scraping, private socket
  or SQLite access from browser code, WebSocket, external network call, cloud,
  telemetry, persistence, or hardware path.

The accepted P1 files must remain byte-identical throughout P2:

| File | SHA-256 at the evidence baseline |
|---|---|
| `studio/index.html` | `b53a73f667a22caeb5c98f7ac57f51d444311f95f65bf53005723ba09c608660` |
| `studio/studio.css` | `16e5d0d4545a123c1ccd2a08449f3c8863304735a75f011f130f20f92d20ea01` |
| `studio/fixtures.js` | `19a6f1382780e6e39e961c8498c8cc9fb2030f382003dda931d2a33da806f864` |
| `studio/app.js` | `9b15474eee9dea77371caffedbb3cedf1c2542a5fd9870be105e0518f599d9ca` |

P2 acceptance requires the frozen contract, all focused tests, Ruff, Pyright,
the full non-hardware pytest suite, and Ubuntu plus macOS Intel Quality-gate
success on the exact candidate SHA. No hardware, release, or package-publication
evidence is required or implied.

## 10. P3 handoff and residual risks

P2 delivers the typed adapter, secure host, DOM-independent controller, and
their tests. P3 exclusively owns installed-wheel Studio asset composition,
`hiyelx studio` CLI integration, browser launch orchestration, loading the
controller into the application, live DOM wiring, and installed-wheel live
dashboard evidence. P3 may compose but must not weaken this security contract
or redesign the accepted P1 presentation without separate authorization.

This boundary resolves the apparent P1/P2 composition conflict: P2 tests the
controller independently while preserving P1 bytes; P3 performs the authorized
composition. Remaining accepted risks are an explicit lack of IPv6 support,
temporary sanitized discovery failure during runtime artifact races, and no
protection against a compromised same-user environment. None authorizes a
fallback external bind, partial discovery result, persistent credential, or
runtime mutation.
