import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
CLIENT = ROOT / "studio" / "host-client.js"

NODE_PROBE = r"""
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

const context = { URL };
vm.runInNewContext(fs.readFileSync(process.argv[1], "utf8"), context, {
  filename: "studio/host-client.js",
  timeout: 1000,
});
const api = context.HiyelxStudioHostClient;
assert.ok(api);
assert.deepEqual(Object.keys(api), ["createController"]);

const ORIGIN = "http://127.0.0.1:43123";
const CAPABILITY = "A".repeat(43);

function preview(overrides = {}) {
  const value = {
    resources: [{
      health_status: "healthy",
      health_summary: null,
      identity: "sim_motor",
      kind: "motor",
      lifecycle_state: "running",
      state: {
        angular_position_radians: 0.42,
        angular_velocity_radians_per_second: 0.18,
        revision: 3,
        simulation_time_seconds: 12.4,
      },
    }],
    runtime_state: "running",
    schema_version: "1",
  };
  if (overrides.resource) Object.assign(value.resources[0], overrides.resource);
  if (overrides.state) Object.assign(value.resources[0].state, overrides.state);
  if (overrides.root) Object.assign(value, overrides.root);
  return value;
}

const metadata = Object.freeze({
  app_version: "0.2.0a1",
  host_version: "1",
  ready: true,
  schema_version: "1",
});
const sessionList = Object.freeze({schema_version: "1", sessions: ["alpha", "beta"]});

function errorDocument(code) {
  const values = {
    preview_unavailable: ["Studio preview is temporarily unavailable.", 503],
    session_not_running: ["The selected session is not running.", 404],
    application_error: ["Studio could not read this snapshot.", 500],
  };
  return {
    document: {error: {code, message: values[code][0]}, schema_version: "1"},
    status: values[code][1],
  };
}

function response(document, status, path, url = null) {
  return {
    json: async () => document,
    ok: status === 200,
    status,
    url: url ?? `${ORIGIN}${path}`,
  };
}

class Transport {
  constructor() {
    this.calls = [];
    this.queue = [];
  }

  enqueue(document, status = 200, url = null) {
    this.queue.push((path) => Promise.resolve(response(document, status, path, url)));
  }

  fail() {
    this.queue.push(async () => { throw new Error("private network detail"); });
  }

  defer() {
    let resolve;
    const promise = new Promise((complete) => { resolve = complete; });
    this.queue.push((path) => promise.then(({document, status = 200, url = null}) => (
      response(document, status, path, url)
    )));
    return { resolve: (document, status = 200, url = null) => resolve({document, status, url}) };
  }

  fetch(path, options) {
    this.calls.push({path, options});
    assert.ok(this.queue.length > 0, `unexpected request to ${path}`);
    return this.queue.shift()(path);
  }
}

class Timers {
  constructor() {
    this.next = 1;
    this.jobs = new Map();
  }

  set(callback, delay) {
    const id = this.next;
    this.next += 1;
    this.jobs.set(id, {callback, delay});
    return id;
  }

  clear(id) {
    this.jobs.delete(id);
  }

  async run(expectedDelay) {
    assert.equal(this.jobs.size, 1);
    const [id, job] = this.jobs.entries().next().value;
    assert.equal(job.delay, expectedDelay);
    this.jobs.delete(id);
    job.callback();
    await settle();
  }
}

class Visibility {
  constructor(visible = true) {
    this.visible = visible;
    this.listeners = new Set();
  }

  isVisible() { return this.visible; }

  subscribe(listener) {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }

  set(visible) {
    this.visible = visible;
    [...this.listeners].forEach((listener) => listener());
  }
}

class FakeAbortController {
  constructor() {
    this.signal = {aborted: false};
  }

  abort() { this.signal.aborted = true; }
}

async function settle() {
  for (let index = 0; index < 12; index += 1) await Promise.resolve();
}

function make(transport = new Transport(), overrides = {}) {
  const clock = overrides.clock ?? {value: 0};
  const timers = overrides.timers ?? new Timers();
  const visibility = overrides.visibility ?? new Visibility();
  const historyCalls = overrides.historyCalls ?? [];
  const abortControllers = [];
  const location = {
    hash: overrides.hash ?? `#capability=${CAPABILITY}`,
    origin: overrides.origin ?? ORIGIN,
    pathname: overrides.pathname ?? "/",
    search: overrides.search ?? "",
  };
  const history = {
    state: {safe: true},
    replaceState: (...args) => historyCalls.push(args),
  };
  const controller = api.createController({
    createAbortController: () => {
      const value = new FakeAbortController();
      abortControllers.push(value);
      return value;
    },
    fetch: transport.fetch.bind(transport),
    history,
    location,
    now: () => clock.value,
    setTimer: timers.set.bind(timers),
    clearTimer: timers.clear.bind(timers),
    visibility,
  });
  return {
    abortControllers,
    clock,
    controller,
    historyCalls,
    location,
    timers,
    transport,
    visibility,
  };
}

async function rejectsCode(operation, code) {
  try {
    await operation;
    assert.fail(`expected ${code}`);
  } catch (error) {
    assert.equal(error.name, "StudioClientError");
    assert.equal(error.code, code);
    assert.equal(error.message, "Studio client operation failed.");
  }
}

async function pollDocument(document) {
  const transport = new Transport();
  transport.enqueue(document);
  const harness = make(transport);
  harness.controller.selectSession("alpha");
  harness.controller.start();
  await harness.timers.run(0);
  return harness;
}

const cases = {
  async capability() {
    const harness = make();
    assert.equal(harness.historyCalls.length, 1);
    assert.deepEqual(harness.historyCalls[0], [{safe: true}, "", "/"]);
    assert.ok(!JSON.stringify(harness.controller).includes(CAPABILITY));
    assert.ok(!JSON.stringify(harness.controller.getState()).includes(CAPABILITY));
    harness.controller.dispose();

    for (const hash of ["", "#capability=short", `#other=${CAPABILITY}`,
      `#capability=${CAPABILITY}=`, `#capability=${CAPABILITY}&extra=1`]) {
      const historyCalls = [];
      assert.throws(
        () => make(new Transport(), {hash, historyCalls}),
        (error) => error.name === "StudioClientError" && error.code === "invalid_capability",
      );
      assert.equal(historyCalls.length, 1);
      assert.equal(historyCalls[0][2], "/");
    }
  },

  async transport() {
    const transport = new Transport();
    transport.enqueue(metadata);
    transport.enqueue(sessionList);
    const harness = make(transport);
    assert.equal(
      JSON.stringify(await harness.controller.fetchMetadata()),
      JSON.stringify(metadata),
    );
    assert.deepEqual(Array.from(await harness.controller.refreshSessions()), ["alpha", "beta"]);
    assert.deepEqual(transport.calls.map((call) => call.path), [
      "/api/v1/meta", "/api/v1/sessions",
    ]);
    for (const call of transport.calls) {
      assert.ok(!call.path.includes(CAPABILITY));
      assert.equal(call.options.method, "GET");
      assert.equal(call.options.cache, "no-store");
      assert.equal(call.options.credentials, "omit");
      assert.equal(call.options.redirect, "error");
      assert.equal(call.options.referrerPolicy, "no-referrer");
      assert.equal(
        JSON.stringify(call.options.headers),
        JSON.stringify({"X-HIYELX-Studio-Capability": CAPABILITY}),
      );
    }
    harness.controller.dispose();

    const redirected = new Transport();
    redirected.enqueue(metadata, 200, "https://example.invalid/api/v1/meta");
    const external = make(redirected);
    await rejectsCode(external.controller.fetchMetadata(), "invalid_response");
    external.controller.dispose();
  },

  async metadata_schema() {
    const invalid = [
      {host_version: "1", ready: true, schema_version: "1"},
      {...metadata, extra: true},
      {...metadata, ready: "true"},
      {...metadata, schema_version: "2"},
      {...metadata, host_version: 1},
    ];
    for (const document of invalid) {
      const transport = new Transport();
      transport.enqueue(document);
      const harness = make(transport);
      await rejectsCode(
        harness.controller.fetchMetadata(),
        document.schema_version === "2" ? "schema_unsupported" : "invalid_response",
      );
      harness.controller.dispose();
    }
  },

  async session_schema() {
    const invalid = [
      {sessions: ["alpha"]},
      {...sessionList, extra: true},
      {schema_version: "1", sessions: "alpha"},
      {schema_version: "1", sessions: ["beta", "alpha"]},
      {schema_version: "1", sessions: ["alpha", "alpha"]},
      {schema_version: "1", sessions: ["INVALID"]},
      {schema_version: "2", sessions: []},
    ];
    for (const document of invalid) {
      const transport = new Transport();
      transport.enqueue(document);
      const harness = make(transport);
      await rejectsCode(
        harness.controller.refreshSessions(),
        document.schema_version === "2" ? "schema_unsupported" : "invalid_response",
      );
      harness.controller.dispose();
    }
  },

  async preview_schema() {
    const missing = preview();
    delete missing.runtime_state;
    const extra = preview({root: {extra: true}});
    const invalid = [
      missing,
      extra,
      preview({root: {schema_version: "2"}}),
      preview({root: {runtime_state: "private"}}),
      preview({root: {resources: []}}),
      preview({resource: {kind: "camera"}}),
      preview({resource: {health_status: "private"}}),
      preview({resource: {health_summary: "/tmp/private"}}),
      preview({state: {revision: true}}),
      preview({state: {revision: -1}}),
      preview({state: {simulation_time_seconds: -1}}),
    ];
    for (const document of invalid) {
      const harness = await pollDocument(document);
      const expected = document.schema_version === "2" ? "unsupported" : "error";
      assert.equal(harness.controller.getState().phase, expected);
      assert.equal(harness.controller.getState().snapshot, null);
      harness.controller.dispose();
    }
  },

  async non_finite() {
    for (const state of [
      {angular_position_radians: Number.NaN},
      {angular_velocity_radians_per_second: Number.POSITIVE_INFINITY},
      {simulation_time_seconds: Number.NEGATIVE_INFINITY},
    ]) {
      const harness = await pollDocument(preview({state}));
      assert.equal(harness.controller.getState().phase, "error");
      assert.equal(harness.controller.getState().error, "invalid_response");
      harness.controller.dispose();
    }
  },

  async single_flight() {
    const transport = new Transport();
    transport.enqueue(preview());
    const deferred = transport.defer();
    const harness = make(transport);
    harness.controller.selectSession("alpha");
    harness.controller.start();
    await harness.timers.run(0);
    assert.equal(harness.controller.getState().phase, "fresh");
    assert.equal(harness.timers.jobs.size, 1);
    await harness.timers.run(1000);
    assert.equal(transport.calls.length, 2);
    assert.equal(harness.timers.jobs.size, 0);
    harness.controller.start();
    assert.equal(transport.calls.length, 2);
    deferred.resolve(preview());
    await settle();
    assert.equal(harness.controller.getState().phase, "unchanged");
    assert.equal(harness.timers.jobs.size, 1);
    harness.controller.dispose();
  },

  async full_equality() {
    const transport = new Transport();
    transport.enqueue(preview());
    transport.enqueue(preview());
    transport.enqueue(preview({resource: {health_status: "degraded"}}));
    const harness = make(transport);
    harness.controller.selectSession("alpha");
    harness.controller.start();
    await harness.timers.run(0);
    assert.equal(harness.controller.getState().phase, "fresh");
    await harness.timers.run(1000);
    assert.equal(harness.controller.getState().phase, "unchanged");
    await harness.timers.run(1000);
    assert.equal(harness.controller.getState().phase, "fresh");
    assert.equal(harness.controller.getState().snapshot.resources[0].state.revision, 3);
    assert.equal(harness.controller.getState().snapshot.resources[0].health_status, "degraded");
    harness.controller.dispose();
  },

  async transitions() {
    const transport = new Transport();
    transport.enqueue(preview());
    for (let count = 0; count < 3; count += 1) {
      const failure = errorDocument("preview_unavailable");
      transport.enqueue(failure.document, failure.status);
    }
    transport.enqueue(preview());
    const clock = {value: 1000};
    const harness = make(transport, {clock});
    harness.controller.selectSession("alpha");
    harness.controller.start();
    await harness.timers.run(0);
    assert.equal(harness.controller.getState().phase, "fresh");
    clock.value = 2000;
    await harness.timers.run(1000);
    assert.equal(harness.controller.getState().phase, "stale");
    assert.equal(harness.controller.getState().snapshotAgeSeconds, 1);
    clock.value = 3000;
    await harness.timers.run(1000);
    assert.equal(harness.controller.getState().phase, "stale");
    clock.value = 4000;
    await harness.timers.run(1000);
    assert.equal(harness.controller.getState().phase, "unavailable");
    assert.equal(harness.controller.getState().consecutiveFailures, 3);
    clock.value = 5000;
    await harness.timers.run(1000);
    assert.equal(harness.controller.getState().phase, "unchanged");
    assert.equal(harness.controller.getState().consecutiveFailures, 0);
    assert.equal(harness.controller.getState().error, null);
    harness.controller.dispose();
  },

  async monotonic_freshness() {
    const transport = new Transport();
    transport.enqueue(preview());
    const clock = {value: 1000};
    const harness = make(transport, {clock});
    harness.controller.selectSession("alpha");
    harness.controller.start();
    await harness.timers.run(0);
    clock.value = 1500;
    assert.equal(harness.controller.getState().snapshotAgeSeconds, 0.5);
    clock.value = 1200;
    assert.equal(harness.controller.getState().snapshotAgeSeconds, 0.5);
    assert.equal(harness.controller.getState().snapshot.snapshot_time, undefined);
    harness.controller.dispose();
  },

  async generation_isolation() {
    const transport = new Transport();
    const alpha = transport.defer();
    const harness = make(transport);
    harness.controller.selectSession("alpha");
    harness.controller.start();
    await harness.timers.run(0);
    harness.controller.selectSession("beta");
    assert.equal(harness.controller.getState().generation, 2);
    assert.equal(harness.controller.getState().snapshot, null);
    assert.equal(harness.abortControllers[0].signal.aborted, true);
    alpha.resolve(preview({state: {revision: 99}}));
    await settle();
    assert.equal(harness.controller.getState().selectedSession, "beta");
    assert.equal(harness.controller.getState().snapshot, null);
    assert.equal(harness.timers.jobs.size, 1);
    transport.enqueue(preview({state: {revision: 4}}));
    await harness.timers.run(0);
    assert.equal(harness.controller.getState().selectedSession, "beta");
    assert.equal(harness.controller.getState().snapshot.resources[0].state.revision, 4);
    assert.deepEqual(transport.calls.map((call) => call.path), [
      "/api/v1/sessions/alpha/preview",
      "/api/v1/sessions/beta/preview",
    ]);
    harness.controller.dispose();
  },

  async disposal() {
    const transport = new Transport();
    const deferred = transport.defer();
    const harness = make(transport);
    const states = [];
    harness.controller.subscribe((state) => states.push(state.phase));
    harness.controller.selectSession("alpha");
    harness.controller.start();
    await harness.timers.run(0);
    harness.controller.dispose();
    assert.equal(harness.controller.getState().phase, "disposed");
    assert.equal(harness.abortControllers[0].signal.aborted, true);
    deferred.resolve(preview());
    await settle();
    assert.equal(harness.controller.getState().phase, "disposed");
    assert.equal(harness.timers.jobs.size, 0);
    assert.equal(states.at(-1), "disposed");
  },

  async visibility() {
    const transport = new Transport();
    transport.enqueue(preview());
    transport.enqueue(preview());
    transport.enqueue(preview());
    const clock = {value: 1000};
    const visibility = new Visibility();
    const harness = make(transport, {clock, visibility});
    harness.controller.selectSession("alpha");
    harness.controller.start();
    await harness.timers.run(0);
    visibility.set(false);
    assert.equal(harness.controller.getState().phase, "paused");
    assert.equal(harness.timers.jobs.size, 0);
    clock.value = 6000;
    assert.equal(harness.controller.getState().snapshotAgeSeconds, 5);
    assert.equal(transport.calls.length, 1);
    visibility.set(true);
    assert.equal(harness.controller.getState().phase, "stale");
    await harness.timers.run(0);
    assert.equal(harness.controller.getState().phase, "unchanged");
    assert.equal(harness.controller.getState().snapshotAgeSeconds, 0);
    assert.equal(transport.calls.length, 2);
    harness.controller.pause();
    assert.equal(harness.controller.getState().phase, "paused");
    assert.equal(harness.timers.jobs.size, 0);
    visibility.set(false);
    visibility.set(true);
    assert.equal(harness.controller.getState().phase, "paused");
    assert.equal(harness.timers.jobs.size, 0);
    harness.controller.start();
    assert.equal(harness.controller.getState().phase, "stale");
    await harness.timers.run(0);
    assert.equal(harness.controller.getState().phase, "unchanged");
    assert.equal(transport.calls.length, 3);
    harness.controller.dispose();
  },

  async sanitized_errors() {
    const transport = new Transport();
    transport.fail();
    const harness = make(transport);
    harness.controller.selectSession("alpha");
    harness.controller.start();
    await harness.timers.run(0);
    const state = harness.controller.getState();
    assert.equal(state.phase, "disconnected");
    assert.equal(state.error, "host_disconnected");
    assert.ok(!JSON.stringify(state).includes("private network detail"));
    harness.controller.dispose();
  },
};

(async () => {
  const name = process.argv[2];
  assert.ok(Object.hasOwn(cases, name), `unknown case ${name}`);
  await cases[name]();
  process.stdout.write(JSON.stringify({case: name, marker: "studio-host-client=passed"}));
})().catch((error) => {
  process.stderr.write(`${error.stack || error}\n`);
  process.exitCode = 1;
});
"""


@pytest.mark.parametrize(
    "case",
    (
        "capability",
        "transport",
        "metadata_schema",
        "session_schema",
        "preview_schema",
        "non_finite",
        "single_flight",
        "full_equality",
        "transitions",
        "monotonic_freshness",
        "generation_isolation",
        "disposal",
        "visibility",
        "sanitized_errors",
    ),
)
def test_host_client_behavior(case: str) -> None:
    assert _run_node(case) == {
        "case": case,
        "marker": "studio-host-client=passed",
    }


def test_controller_has_no_dom_persistence_or_mutation_transport() -> None:
    source = CLIENT.read_text()

    for prohibited in (
        "localStorage",
        "sessionStorage",
        "indexedDB",
        "document.",
        "querySelector",
        "WebSocket",
        "EventSource",
        "XMLHttpRequest",
        "serviceWorker",
        "console.",
        "ws://",
        "wss://",
        'method: "POST"',
        'method: "PUT"',
        'method: "PATCH"',
        'method: "DELETE"',
    ):
        assert prohibited not in source
    assert "fetchFn(path" in source
    assert "X-HIYELX-Studio-Capability" in source
    assert re.findall(r'"(/api/v1/[^"`]*)"', source) == [
        "/api/v1/meta",
        "/api/v1/sessions",
    ]


def _run_node(case: str) -> dict[str, str]:
    node = shutil.which("node")
    assert node is not None, "Node.js is required for Studio controller tests"
    try:
        result = subprocess.run(
            [node, "-e", NODE_PROBE, str(CLIENT.resolve()), case],
            cwd=ROOT,
            shell=False,
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except subprocess.TimeoutExpired:
        raise AssertionError(f"Studio controller probe timed out for {case}") from None

    failure = (
        f"Studio controller probe failed for {case} (exit {result.returncode}); "
        f"stdout={_safe_output(result.stdout)!r}; stderr={_safe_output(result.stderr)!r}"
    )
    assert result.returncode == 0, failure
    assert result.stderr == "", failure
    return json.loads(result.stdout)


def _safe_output(value: str) -> str:
    value = value.replace(str(ROOT), "<repo>").replace(str(Path.home()), "<home>")
    return re.sub(
        r"(?i)\b(token|capability|password|secret|authorization)(\s*[:=]\s*)\S+",
        r"\1\2<redacted>",
        value,
    )
