import json
import re
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
STUDIO = ROOT / "studio"


def _safe_output(value: str | bytes | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        value = value.decode("utf-8", errors="replace")
    value = value.replace(str(ROOT), "<repo>").replace(str(Path.home()), "<home>")
    value = re.sub(r"http://127\.0\.0\.1:\d+", "<loopback>", value)
    return re.sub(
        r"(?i)\b(token|password|secret|authorization|capability)(\s*[:=]\s*)\S+",
        r"\1\2<redacted>",
        value,
    )


def test_live_dashboard_composes_real_controller_and_fails_closed() -> None:
    node = shutil.which("node")
    assert node is not None, "Node.js is required for the live Studio composition test"
    script = r"""
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

const hostClientSource = fs.readFileSync(process.argv[1], "utf8");
const appSource = fs.readFileSync(process.argv[2], "utf8");
const CAPABILITY = "c".repeat(43);
const ORIGIN = "http://127.0.0.1:43123";

class Element {
  constructor(tagName, id = "") {
    this.tagName = tagName.toUpperCase();
    this.id = id;
    this.className = "";
    this.dataset = {};
    this.hidden = false;
    this.disabled = false;
    this.value = "";
    this.attributes = new Map();
    this.children = [];
    this.listeners = new Map();
    this.parentNode = null;
    this._text = "";
  }

  get textContent() {
    return this._text + this.children.map((child) => child.textContent).join("");
  }

  set textContent(value) {
    this._text = String(value);
    this.children = [];
  }

  append(...children) {
    for (const child of children) {
      child.parentNode = this;
      this.children.push(child);
    }
  }

  replaceChildren(...children) {
    this.children.forEach((child) => { child.parentNode = null; });
    this.children = [];
    this._text = "";
    this.append(...children);
  }

  setAttribute(name, value) {
    this.attributes.set(name, String(value));
  }

  getAttribute(name) {
    return this.attributes.get(name) ?? null;
  }

  addEventListener(name, listener) {
    if (!this.listeners.has(name)) this.listeners.set(name, new Set());
    this.listeners.get(name).add(listener);
  }

  removeEventListener(name, listener) {
    this.listeners.get(name)?.delete(listener);
  }

  dispatchEvent(event) {
    event.target = this;
    for (const listener of [...(this.listeners.get(event.type) ?? [])]) listener(event);
    return true;
  }

  focus() {
    this.ownerDocument.activeElement = this;
  }
}

class FakeDocument {
  constructor() {
    this.visibilityState = "visible";
    this.activeElement = null;
    this.listeners = new Map();
    this.elements = new Map();
    this.body = this.make("body", "body");
    const tags = {
      "connection-badge": "span",
      "connection-label": "span",
      "empty-copy": "p",
      "empty-state": "div",
      "empty-title": "h3",
      freshness: "span",
      "resource-count": "strong",
      "resource-grid": "div",
      "runtime-state": "strong",
      "session-select": "select",
      "snapshot-state": "strong",
      "state-message": "div",
      "state-message-text": "span",
      "state-pill": "span",
    };
    for (const [id, tag] of Object.entries(tags)) this.make(tag, id);
  }

  make(tag, id = "") {
    const element = new Element(tag, id);
    element.ownerDocument = this;
    if (id) this.elements.set(id, element);
    return element;
  }

  createElement(tag) {
    return this.make(tag);
  }

  getElementById(id) {
    return this.elements.get(id) ?? null;
  }

  addEventListener(name, listener) {
    if (!this.listeners.has(name)) this.listeners.set(name, new Set());
    this.listeners.get(name).add(listener);
  }

  removeEventListener(name, listener) {
    this.listeners.get(name)?.delete(listener);
  }

  setVisibility(value) {
    this.visibilityState = value;
    for (const listener of [...(this.listeners.get("visibilitychange") ?? [])]) listener();
  }
}

class Deferred {
  constructor() {
    this.promise = new Promise((resolve, reject) => {
      this.resolve = resolve;
      this.reject = reject;
    });
  }
}

function preview(identity, position = 1.25, revision = 7) {
  return {
    resources: [{
      health_status: "healthy",
      health_summary: null,
      identity,
      kind: "motor",
      lifecycle_state: "running",
      state: {
        angular_position_radians: position,
        angular_velocity_radians_per_second: -0.5,
        revision,
        simulation_time_seconds: 2.5,
      },
    }],
    runtime_state: "running",
    schema_version: "1",
  };
}

const errorDocuments = {
  application_error: [500, "Studio could not read this snapshot."],
  preview_unavailable: [503, "Studio preview is temporarily unavailable."],
  preview_unsupported: [422, "This Studio version cannot read this preview schema."],
  session_not_running: [404, "The selected session is not running."],
};

function errorSpec(code) {
  const [status, message] = errorDocuments[code];
  return { body: { error: { code, message }, schema_version: "1" }, status };
}

function response(spec, path) {
  const status = spec.status ?? 200;
  return {
    ok: status === 200,
    status,
    url: `${ORIGIN}${path}`,
    async json() { return spec.body; },
  };
}

function findByClass(root, className) {
  const matches = [];
  function visit(node) {
    if (node.className.split(/\s+/).includes(className)) matches.push(node);
    node.children.forEach(visit);
  }
  visit(root);
  return matches;
}

async function settle() {
  for (let index = 0; index < 5; index += 1) {
    await new Promise((resolve) => setImmediate(resolve));
  }
}

function makeHarness({ hash = `#capability=${CAPABILITY}`, sessions = ["alpha"], previews = {} } = {}) {
  const document = new FakeDocument();
  const location = { hash, origin: ORIGIN, pathname: "/index.html", search: "" };
  const historyCalls = [];
  const requests = [];
  const windowListeners = new Map();
  const timers = new Map();
  const queues = new Map(Object.entries(previews).map(([session, items]) => [session, [...items]]));
  let nextTimer = 1;
  let clock = 0;
  let aborts = 0;

  class FakeAbortController {
    constructor() {
      this.signal = { aborted: false };
    }
    abort() {
      if (!this.signal.aborted) aborts += 1;
      this.signal.aborted = true;
    }
  }

  async function fetchFn(path, options) {
    assert.ok(path.startsWith("/api/v1/"), "only same-origin Studio API paths are allowed");
    requests.push({ headers: options.headers, method: options.method, path });
    let spec;
    if (path === "/api/v1/meta") {
      spec = { body: { app_version: "0.2.0a1", host_version: "1", ready: true, schema_version: "1" } };
    } else if (path === "/api/v1/sessions") {
      spec = { body: { schema_version: "1", sessions } };
    } else {
      const match = /^\/api\/v1\/sessions\/([^/]+)\/preview$/.exec(path);
      assert.ok(match, `unexpected API path: ${path}`);
      const queue = queues.get(match[1]) ?? [];
      assert.ok(queue.length > 0, `missing preview response for ${match[1]}`);
      spec = queue.shift();
    }
    if (spec instanceof Deferred) spec = await spec.promise;
    if (spec.reject) throw new Error(spec.reject);
    return response(spec, path);
  }

  const context = {
    AbortController: FakeAbortController,
    URL,
    clearTimeout(id) { timers.delete(id); },
    console: { error() {}, log() {}, warn() {} },
    document,
    fetch: fetchFn,
    history: {
      state: null,
      replaceState(state, title, replacement) {
        historyCalls.push({ replacement, state, title });
        location.hash = "";
      },
    },
    location,
    performance: { now: () => clock },
    setTimeout(callback, delay) {
      const id = nextTimer;
      nextTimer += 1;
      timers.set(id, { callback, delay });
      return id;
    },
  };
  context.addEventListener = (name, listener) => {
    if (!windowListeners.has(name)) windowListeners.set(name, new Set());
    windowListeners.get(name).add(listener);
  };
  context.removeEventListener = (name, listener) => windowListeners.get(name)?.delete(listener);
  context.dispatchWindow = (name) => {
    for (const listener of [...(windowListeners.get(name) ?? [])]) listener({ type: name });
  };
  context.window = context;
  context.globalThis = context;
  vm.createContext(context);

  async function load() {
    vm.runInContext(hostClientSource, context, { filename: "studio/host-client.js", timeout: 1000 });
    vm.runInContext(appSource, context, { filename: "studio/app.js", timeout: 1000 });
    await settle();
  }

  async function runNextTimer() {
    assert.ok(timers.size > 0, "expected a scheduled controller poll");
    const [id, timer] = [...timers.entries()][0];
    timers.delete(id);
    timer.callback();
    await settle();
    return timer.delay;
  }

  return {
    advance(value) { clock += value; },
    dispatchWindow: context.dispatchWindow,
    document,
    get aborts() { return aborts; },
    historyCalls,
    load,
    location,
    requests,
    runNextTimer,
    serializeDom() {
      return [...document.elements.values()].map((element) => element.textContent).join("|");
    },
    get timerCount() { return timers.size; },
  };
}

async function startPreview(harness) {
  await harness.load();
  assert.deepEqual(harness.requests.map(({ path }) => path), ["/api/v1/meta", "/api/v1/sessions"]);
  await harness.runNextTimer();
}

async function verifyPreviewFailure(spec, expectedPhase, expectedText) {
  const harness = makeHarness({ previews: { alpha: [spec] } });
  await startPreview(harness);
  assert.equal(harness.document.body.dataset.phase, expectedPhase);
  assert.equal(harness.document.getElementById("state-message-text").textContent, expectedText);
  assert.equal(harness.document.getElementById("runtime-state").textContent, "—");
  assert.equal(harness.document.getElementById("resource-count").textContent, "0");
  assert.equal(harness.document.getElementById("resource-grid").children.length, 0);
  const dom = harness.serializeDom();
  for (const privateValue of [CAPABILITY, ORIGIN, "/private/", "secret", "pid=123"]) {
    assert.ok(!dom.includes(privateValue), `private value reached DOM: ${privateValue}`);
  }
}

(async () => {
  const lateAlpha = new Deferred();
  const pendingBeta = new Deferred();
  const snapshotAlpha = preview("sim_alpha");
  const snapshotBeta = preview("sim_beta", 2.5, 8);
  const recoveredBeta = preview("sim_beta", 3.5, 9);
  const harness = makeHarness({
    sessions: ["alpha", "beta"],
    previews: {
      alpha: [
        { body: snapshotAlpha },
        { body: snapshotAlpha },
        lateAlpha,
      ],
      beta: [
        { body: snapshotBeta },
        errorSpec("preview_unavailable"),
        errorSpec("preview_unavailable"),
        errorSpec("preview_unavailable"),
        { body: recoveredBeta },
        pendingBeta,
      ],
    },
  });
  await harness.load();

  assert.equal(harness.historyCalls.length, 1);
  assert.equal(harness.historyCalls[0].replacement, "/index.html");
  assert.equal(harness.location.hash, "");
  assert.deepEqual(harness.requests.map(({ path }) => path), ["/api/v1/meta", "/api/v1/sessions"]);
  const select = harness.document.getElementById("session-select");
  assert.equal(select.disabled, false);
  assert.deepEqual(select.children.map(({ value }) => value), ["alpha", "beta"]);
  assert.equal(select.value, "alpha");
  assert.equal(harness.document.body.dataset.phase, "connecting");
  assert.equal(harness.document.getElementById("resource-grid").children.length, 0);

  await harness.runNextTimer();
  assert.deepEqual(harness.requests.slice(0, 3).map(({ path }) => path), [
    "/api/v1/meta",
    "/api/v1/sessions",
    "/api/v1/sessions/alpha/preview",
  ]);
  assert.equal(harness.document.body.dataset.phase, "fresh");
  assert.equal(harness.document.getElementById("runtime-state").textContent, "running");
  assert.equal(harness.document.getElementById("resource-count").textContent, "1");
  assert.equal(harness.document.getElementById("snapshot-state").textContent, "Fresh");
  const grid = harness.document.getElementById("resource-grid");
  const firstCard = grid.children[0];
  assert.ok(firstCard.textContent.includes("sim_alpha"));
  assert.ok(firstCard.textContent.includes("1.250"));
  assert.ok(firstCard.textContent.includes("-0.500"));
  assert.ok(firstCard.textContent.includes("2.5"));
  assert.ok(firstCard.textContent.includes("7"));
  assert.deepEqual(findByClass(firstCard, "metric-unit").map(({ textContent }) => textContent), [
    "rad", "rad/s", "simulated s", "state mutations",
  ]);

  select.focus();
  harness.advance(1000);
  assert.equal(await harness.runNextTimer(), 1000);
  assert.equal(harness.document.body.dataset.phase, "unchanged");
  assert.ok(harness.document.getElementById("freshness").textContent.includes("unchanged"));
  assert.strictEqual(grid.children[0], firstCard, "unchanged poll must preserve the resource card node");
  assert.strictEqual(harness.document.activeElement, select, "poll rendering must preserve select focus");

  harness.advance(1000);
  await harness.runNextTimer();
  select.value = "beta";
  select.dispatchEvent({ type: "change" });
  assert.equal(harness.document.body.dataset.phase, "connecting");
  assert.equal(grid.children.length, 0, "session switch must clear the previous snapshot immediately");
  lateAlpha.resolve({ body: preview("late_alpha", 99, 99) });
  await settle();
  assert.equal(harness.document.body.dataset.phase, "connecting");
  assert.equal(grid.children.length, 0, "late previous-generation data must not reach the DOM");
  await harness.runNextTimer();
  assert.equal(harness.document.body.dataset.phase, "fresh");
  assert.ok(grid.children[0].textContent.includes("sim_beta"));
  assert.ok(!grid.children[0].textContent.includes("late_alpha"));
  assert.strictEqual(harness.document.activeElement, select);

  harness.advance(1000);
  await harness.runNextTimer();
  assert.equal(harness.document.body.dataset.phase, "stale");
  assert.ok(grid.children[0].textContent.includes("sim_beta"));
  harness.advance(1000);
  await harness.runNextTimer();
  assert.equal(harness.document.body.dataset.phase, "stale");
  harness.advance(1000);
  await harness.runNextTimer();
  assert.equal(harness.document.body.dataset.phase, "unavailable");
  assert.ok(grid.children[0].textContent.includes("sim_beta"));
  harness.advance(1000);
  await harness.runNextTimer();
  assert.equal(harness.document.body.dataset.phase, "fresh");
  assert.ok(grid.children[0].textContent.includes("3.500"));

  harness.document.setVisibility("hidden");
  assert.equal(harness.document.body.dataset.phase, "paused");
  assert.ok(harness.document.getElementById("freshness").textContent.startsWith("Paused"));
  harness.document.setVisibility("visible");
  assert.equal(harness.document.body.dataset.phase, "stale");
  await harness.runNextTimer();
  harness.dispatchWindow("pagehide");
  assert.equal(harness.document.body.dataset.phase, "disposed");
  assert.equal(harness.timerCount, 0);
  assert.ok(harness.aborts >= 1, "dispose must abort an in-flight preview");
  harness.dispatchWindow("beforeunload");
  pendingBeta.resolve({ body: preview("disposed_late", 88, 88) });
  await settle();
  assert.equal(harness.document.body.dataset.phase, "disposed");
  assert.ok(!harness.serializeDom().includes("disposed_late"));

  for (const request of harness.requests) {
    assert.equal(request.method, "GET");
    assert.ok(request.path.startsWith("/api/v1/"));
    assert.ok(!request.path.includes(CAPABILITY));
    assert.equal(request.headers["X-HIYELX-Studio-Capability"], CAPABILITY);
  }

  await verifyPreviewFailure(
    errorSpec("session_not_running"),
    "stopped",
    "The selected session is not running.",
  );
  await verifyPreviewFailure(
    errorSpec("preview_unsupported"),
    "unsupported",
    "This Studio version cannot read this preview schema.",
  );
  await verifyPreviewFailure(
    { reject: "private path=/private/runtime capability=secret pid=123" },
    "disconnected",
    "The local Studio Host is disconnected.",
  );
  await verifyPreviewFailure(
    errorSpec("application_error"),
    "error",
    "Studio could not read this snapshot.",
  );

  for (const invalidHash of ["", "#capability=invalid"]) {
    const invalid = makeHarness({ hash: invalidHash, previews: {} });
    await invalid.load();
    assert.equal(invalid.document.body.dataset.phase, "disconnected");
    assert.equal(invalid.requests.length, 0);
    assert.equal(invalid.document.getElementById("runtime-state").textContent, "—");
    assert.equal(invalid.document.getElementById("resource-count").textContent, "0");
    assert.equal(invalid.document.getElementById("resource-grid").children.length, 0);
    assert.ok(!invalid.serializeDom().includes("Fixture"));
  }

  const empty = makeHarness({ sessions: [], previews: {} });
  await empty.load();
  assert.equal(empty.document.body.dataset.phase, "idle");
  assert.equal(empty.document.getElementById("connection-label").textContent, "No session");
  assert.equal(empty.document.getElementById("session-select").disabled, true);
  assert.equal(empty.document.getElementById("session-select").children[0].textContent, "No observable sessions");
  assert.equal(empty.requests.length, 2);

  process.stdout.write(JSON.stringify({
    marker: "studio-live-dashboard=passed",
    requests: harness.requests.length,
    states: [
      "connecting", "fresh", "unchanged", "stale", "unavailable", "paused",
      "disposed", "stopped", "unsupported", "disconnected", "error", "idle",
    ],
  }));
})().catch((error) => {
  process.stderr.write(error && error.stack ? error.stack : String(error));
  process.exitCode = 1;
});
"""
    try:
        result = subprocess.run(
            [
                node,
                "-e",
                script,
                str((STUDIO / "host-client.js").resolve()),
                str((STUDIO / "app.js").resolve()),
            ],
            cwd=ROOT,
            shell=False,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise AssertionError(
            "Node live-dashboard probe timed out (10 seconds); "
            f"stdout={_safe_output(exc.stdout)!r}; stderr={_safe_output(exc.stderr)!r}"
        ) from None

    failure = (
        f"Node live-dashboard probe failed (exit {result.returncode}); "
        f"stdout={_safe_output(result.stdout)!r}; stderr={_safe_output(result.stderr)!r}"
    )
    assert result.returncode == 0, failure
    assert result.stderr == "", failure
    assert json.loads(result.stdout) == {
        "marker": "studio-live-dashboard=passed",
        "requests": 11,
        "states": [
            "connecting",
            "fresh",
            "unchanged",
            "stale",
            "unavailable",
            "paused",
            "disposed",
            "stopped",
            "unsupported",
            "disconnected",
            "error",
            "idle",
        ],
    }, failure
