import json
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
STUDIO = ROOT / "studio"
LIVE_HTML = STUDIO / "live.html"
LIVE_APP = STUDIO / "live-app.js"
HOST_CLIENT = STUDIO / "host-client.js"

NODE_PROBE = r"""
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

class FakeElement {
  constructor(tag, id = null) {
    this.tagName = tag.toUpperCase();
    this.id = id;
    this.className = "";
    this.textContent = "";
    this.hidden = false;
    this.disabled = false;
    this.value = "";
    this.selected = false;
    this.dataset = {};
    this.attributes = {};
    this.children = [];
    this.listeners = {};
  }
  setAttribute(name, value) {
    this.attributes[name] = String(value);
  }
  append(...nodes) {
    for (const node of nodes) {
      this.children.push(node);
      if (this.tagName === "SELECT" && node.selected) {
        this.value = node.value;
      }
    }
  }
  replaceChildren(...nodes) {
    this.children = [];
    this.value = "";
    this.append(...nodes);
  }
  addEventListener(type, fn) {
    this.listeners[type] = this.listeners[type] || [];
    this.listeners[type].push(fn);
  }
  removeEventListener(type, fn) {
    if (!this.listeners[type]) return;
    this.listeners[type] = this.listeners[type].filter((item) => item !== fn);
  }
  dispatch(type) {
    for (const fn of [...(this.listeners[type] || [])]) fn();
  }
}

function makeDocument() {
  const ids = [
    "connection-badge",
    "connection-label",
    "state-pill",
    "state-message",
    "state-message-text",
    "freshness",
    "runtime-state",
    "resource-count",
    "snapshot-state",
    "host-version-tag",
    "session-select",
    "refresh-sessions-button",
    "resource-grid",
    "empty-state",
    "empty-title",
    "empty-copy",
    "runtime-package-summary",
    "runtime-models-grid",
  ];
  const elements = new Map();
  for (const id of ids) {
    const tag = id === "session-select" ? "select" : id.endsWith("button") ? "button" : "div";
    elements.set(id, new FakeElement(tag, id));
  }
  return {
    createElement: (tag) => new FakeElement(tag),
    getElementById: (id) => elements.get(id) ?? null,
    elements,
  };
}

function makeAbortController() {
  const signal = { aborted: false };
  return { signal, abort: () => { signal.aborted = true; } };
}

const context = { URL };
vm.runInNewContext(fs.readFileSync(process.argv[1], "utf8"), context, {
  filename: "studio/host-client.js",
  timeout: 1000,
});
vm.runInNewContext(fs.readFileSync(process.argv[2], "utf8"), context, {
  filename: "studio/live-app.js",
  timeout: 1000,
});

const hostClient = context.HiyelxStudioHostClient;
const liveApp = context.HiyelxStudioLiveApp;
assert.ok(hostClient && liveApp);

const ORIGIN = "http://127.0.0.1:43123";
const CAPABILITY = "B".repeat(43);

function makeResponse(doc, status, path) {
  return {
    json: async () => doc,
    ok: status === 200,
    status,
    url: `${ORIGIN}${path}`,
  };
}

function makePreview(position = 0.75, revision = 4) {
  return {
    resources: [{
      health_status: "healthy",
      health_summary: null,
      identity: "sim_motor",
      kind: "motor",
      lifecycle_state: "running",
      state: {
        angular_position_radians: position,
        angular_velocity_radians_per_second: 0.25,
        revision,
        simulation_time_seconds: 5.0,
      },
    }],
    runtime_state: "running",
    schema_version: "1",
  };
}

const meta = { app_version: "0.2.0a1", host_version: "1", ready: true, schema_version: "1" };
const runtimeInfo = {
  package_version: "0.2.0a1",
  registered_models: [
    {
      capabilities: ["can_set_velocity", "has_angular_position"],
      category: "actuator",
      model: "mock.motor",
    },
    {
      capabilities: ["has_encoder_ticks"],
      category: "feedback",
      model: "mock.encoder",
    },
  ],
  schema_version: "1",
  supported_config_schemas: ["1", "2"],
};

async function runCase(name) {
  let clock = 1000;
  let timers = [];
  let visible = true;
  let visibilityListener = null;

  function makeEnv(hash, fetchHandler) {
    const doc = makeDocument();
    const historyState = { replaced: [] };
    const location = { origin: ORIGIN, pathname: "/live", search: "", hash };
    const history = {
      state: null,
      replaceState: (_s, _t, url) => {
        historyState.replaced.push(url);
        location.hash = "";
      },
    };
    const app = liveApp.mountLiveStudio({
      clearTimer: (id) => { timers = timers.filter((t) => t.id !== id); },
      createAbortController: makeAbortController,
      document: doc,
      fetch: fetchHandler,
      history,
      hostClient,
      location,
      now: () => clock,
      setTimer: (fn, delay) => {
        const id = timers.length + 1;
        timers.push({ id, fn, delay });
        return id;
      },
      visibility: {
        isVisible: () => visible,
        subscribe: (fn) => { visibilityListener = fn; return () => {}; },
      },
    });
    return { app, doc, historyState, location };
  }

  async function stepTimer() {
    assert.ok(timers.length > 0, "expected a scheduled poll timer");
    const next = timers.shift();
    next.fn();
    for (let i = 0; i < 10; i += 1) {
      await Promise.resolve();
    }
  }

  if (name === "capability_rejected") {
    const { doc } = makeEnv("", async () => { throw new Error("should not fetch"); });
    return {
      badge: doc.getElementById("connection-label").textContent,
      severity: doc.getElementById("connection-badge").dataset.severity,
      selectDisabled: doc.getElementById("session-select").disabled,
      refreshDisabled: doc.getElementById("refresh-sessions-button").disabled,
      gridHidden: doc.getElementById("resource-grid").hidden,
    };
  }

  if (name === "no_sessions") {
    const { app, doc, historyState } = makeEnv(`#capability=${CAPABILITY}`, async (path) => {
      if (path === "/api/v1/meta") return makeResponse(meta, 200, path);
      if (path === "/api/v1/runtime/info") return makeResponse(runtimeInfo, 200, path);
      if (path === "/api/v1/sessions") {
        return makeResponse({ schema_version: "1", sessions: [] }, 200, path);
      }
      throw new Error(`unexpected ${path}`);
    });
    await app.bootstrapPromise;
    return {
      badge: doc.getElementById("connection-label").textContent,
      severity: doc.getElementById("connection-badge").dataset.severity,
      replaced: historyState.replaced,
      selectDisabled: doc.getElementById("session-select").disabled,
      hostTag: doc.getElementById("host-version-tag").textContent,
      runtimeSummary: doc.getElementById("runtime-package-summary").textContent,
      runtimeModelCount: doc.getElementById("runtime-models-grid").children.length,
      gridHidden: doc.getElementById("resource-grid").hidden,
    };
  }

  if (name === "live_fresh_stale_and_stopped") {
    let previewStep = 0;
    const { app, doc } = makeEnv(`#capability=${CAPABILITY}`, async (path) => {
      if (path === "/api/v1/meta") return makeResponse(meta, 200, path);
      if (path === "/api/v1/runtime/info") return makeResponse(runtimeInfo, 200, path);
      if (path === "/api/v1/sessions") {
        return makeResponse({ schema_version: "1", sessions: ["alpha", "beta"] }, 200, path);
      }
      if (path === "/api/v1/sessions/alpha/preview") {
        previewStep += 1;
        if (previewStep === 1) return makeResponse(makePreview(0.75, 4), 200, path);
        if (previewStep === 2) {
          return makeResponse(
            {
              error: {
                code: "preview_unavailable",
                message: "Studio preview is temporarily unavailable.",
              },
              schema_version: "1",
            },
            503,
            path,
          );
        }
        return makeResponse(
          {
            error: {
              code: "session_not_running",
              message: "The selected session is not running.",
            },
            schema_version: "1",
          },
          404,
          path,
        );
      }
      throw new Error(`unexpected ${path}`);
    });
    await app.bootstrapPromise;
    await stepTimer();
    const fresh = {
      badge: doc.getElementById("connection-label").textContent,
      severity: doc.getElementById("connection-badge").dataset.severity,
      runtimeState: doc.getElementById("runtime-state").textContent,
      resourceCount: doc.getElementById("resource-count").textContent,
      gridHidden: doc.getElementById("resource-grid").hidden,
      cardCount: doc.getElementById("resource-grid").children.length,
    };

    clock += 1000;
    await stepTimer();
    const stale = {
      badge: doc.getElementById("connection-label").textContent,
      severity: doc.getElementById("connection-badge").dataset.severity,
      resourceCount: doc.getElementById("resource-count").textContent,
      gridHidden: doc.getElementById("resource-grid").hidden,
    };

    clock += 1000;
    await stepTimer();
    const stopped = {
      badge: doc.getElementById("connection-label").textContent,
      severity: doc.getElementById("connection-badge").dataset.severity,
      resourceCount: doc.getElementById("resource-count").textContent,
      gridHidden: doc.getElementById("resource-grid").hidden,
    };

    app.dispose();
    return { fresh, stale, stopped };
  }

  if (name === "schema_unsupported") {
    const { app, doc } = makeEnv(`#capability=${CAPABILITY}`, async (path) => {
      if (path === "/api/v1/meta") {
        return makeResponse(
          { app_version: "0.2.0a1", host_version: "1", ready: true, schema_version: "99" },
          200,
          path,
        );
      }
      throw new Error(`unexpected ${path}`);
    });
    await app.bootstrapPromise;
    return {
      badge: doc.getElementById("connection-label").textContent,
      severity: doc.getElementById("connection-badge").dataset.severity,
      gridHidden: doc.getElementById("resource-grid").hidden,
    };
  }

  if (name === "runtime_info_unsupported") {
    const { app, doc } = makeEnv(`#capability=${CAPABILITY}`, async (path) => {
      if (path === "/api/v1/meta") return makeResponse(meta, 200, path);
      if (path === "/api/v1/runtime/info") {
        return makeResponse({ ...runtimeInfo, schema_version: "99" }, 200, path);
      }
      throw new Error(`unexpected ${path}`);
    });
    await app.bootstrapPromise;
    return {
      badge: doc.getElementById("connection-label").textContent,
      severity: doc.getElementById("connection-badge").dataset.severity,
      runtimeModelCount: doc.getElementById("runtime-models-grid").children.length,
      gridHidden: doc.getElementById("resource-grid").hidden,
    };
  }

  if (name === "host_disconnected") {
    const { app, doc } = makeEnv(`#capability=${CAPABILITY}`, async () => {
      throw new TypeError("network down");
    });
    await app.bootstrapPromise;
    return {
      badge: doc.getElementById("connection-label").textContent,
      severity: doc.getElementById("connection-badge").dataset.severity,
      selectDisabled: doc.getElementById("session-select").disabled,
      gridHidden: doc.getElementById("resource-grid").hidden,
    };
  }

  throw new Error(`unknown case ${name}`);
}

runCase(process.argv[3]).then((result) => {
  process.stdout.write(JSON.stringify(result));
}).catch((err) => {
  process.stderr.write(String(err.stack || err));
  process.exit(1);
});
"""


def _run_node(case: str) -> dict[str, object]:
    node = shutil.which("node")
    assert node is not None, "Node.js is required for Studio live composition tests"
    result = subprocess.run(
        [node, "-e", NODE_PROBE, str(HOST_CLIENT.resolve()), str(LIVE_APP.resolve()), case],
        cwd=ROOT,
        shell=False,
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
    )
    assert result.returncode == 0, f"stderr={result.stderr!r} stdout={result.stdout!r}"
    assert result.stderr == ""
    return json.loads(result.stdout)


def test_live_html_never_loads_fixtures_or_p1_app_and_has_no_inline_code() -> None:
    html = LIVE_HTML.read_text(encoding="utf-8")
    assert '<link rel="stylesheet" href="studio.css" />' in html
    assert '<script src="host-client.js" defer></script>' in html
    assert '<script src="live-app.js" defer></script>' in html
    for forbidden in (
        "fixtures.js",
        'src="app.js"',
        "Fixture preview",
        "STATIC PROTOTYPE",
        "onclick=",
        "style=",
    ):
        assert forbidden not in html
    assert LIVE_HTML.stat().st_size < 65_536
    assert LIVE_APP.stat().st_size < 65_536


def test_live_app_has_no_unsafe_dom_storage_or_mutation_primitives() -> None:
    source = LIVE_APP.read_text(encoding="utf-8")
    for prohibited in (
        "innerHTML",
        "outerHTML",
        "insertAdjacentHTML",
        "localStorage",
        "sessionStorage",
        "indexedDB",
        "document.cookie",
        "WebSocket",
        "EventSource",
        "console.",
        "HiyelxStudioFixtures",
        "fixtures.js",
    ):
        assert prohibited not in source


def test_live_app_handles_missing_capability_fail_closed() -> None:
    result = _run_node("capability_rejected")
    assert result == {
        "badge": "Access rejected",
        "severity": "error",
        "selectDisabled": True,
        "refreshDisabled": True,
        "gridHidden": True,
    }


def test_live_app_handles_empty_session_discovery_and_strips_fragment() -> None:
    result = _run_node("no_sessions")
    assert result == {
        "badge": "No active session",
        "severity": "neutral",
        "replaced": ["/live"],
        "selectDisabled": True,
        "hostTag": "HIYELX 0.2.0a1 · HOST v1",
        "runtimeSummary": "hiyelx 0.2.0a1 · Config schemas: v1, v2 · 2 built-in models",
        "runtimeModelCount": 2,
        "gridHidden": True,
    }


def test_live_app_transitions_fresh_to_stale_to_stopped() -> None:
    result = _run_node("live_fresh_stale_and_stopped")
    assert result == {
        "fresh": {
            "badge": "Live · Connected",
            "severity": "success",
            "runtimeState": "running",
            "resourceCount": "1",
            "gridHidden": False,
            "cardCount": 1,
        },
        "stale": {
            "badge": "Stale snapshot",
            "severity": "warning",
            "resourceCount": "1",
            "gridHidden": False,
        },
        "stopped": {
            "badge": "Session stopped",
            "severity": "warning",
            "resourceCount": "0",
            "gridHidden": True,
        },
    }


def test_live_app_fails_closed_on_schema_unsupported_and_host_disconnect() -> None:
    assert _run_node("schema_unsupported") == {
        "badge": "Schema unsupported",
        "severity": "error",
        "gridHidden": True,
    }
    assert _run_node("runtime_info_unsupported") == {
        "badge": "Schema unsupported",
        "severity": "error",
        "runtimeModelCount": 0,
        "gridHidden": True,
    }
    assert _run_node("host_disconnected") == {
        "badge": "Host disconnected",
        "severity": "error",
        "selectDisabled": True,
        "gridHidden": True,
    }
