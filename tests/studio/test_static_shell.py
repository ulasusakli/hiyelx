import json
import re
import shutil
import subprocess
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
STUDIO = ROOT / "studio"


class ShellParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.tags: list[str] = []
        self.ids: set[str] = set()
        self.labels: list[str] = []
        self.label_for: list[str] = []
        self.links: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.tags.append(tag)
        values = dict(attrs)
        if value := values.get("id"):
            self.ids.add(value)
        if tag == "label" and (target := values.get("for")):
            self.label_for.append(target)
        if tag == "a" and (href := values.get("href")):
            self.links.append(href)


def test_static_shell_has_semantic_landmarks_and_labeled_controls() -> None:
    parser = ShellParser()
    parser.feed((STUDIO / "index.html").read_text())

    assert parser.tags.count("header") == 1
    assert parser.tags.count("main") == 1
    assert parser.tags.count("footer") == 1
    assert parser.tags.count("h1") == 1
    assert "lang=\"en\"" in (STUDIO / "index.html").read_text()
    assert {"session-select", "fixture-select"}.issubset(set(parser.label_for))
    assert set(parser.label_for).issubset(parser.ids)
    assert all(link.startswith("#") for link in parser.links)


def test_shell_names_simulation_static_read_only_and_no_live_connection() -> None:
    html = (STUDIO / "index.html").read_text()
    app = (STUDIO / "app.js").read_text()
    fixtures = (STUDIO / "fixtures.js").read_text()

    assert "SIMULATION" in html
    assert "static prototype" in html.lower()
    assert "No runtime is connected" in html
    assert '<select id="session-select" disabled' in html
    assert "<option>Demo · sim_motor</option>" in html
    assert "No session discovery runs in this prototype." in html
    assert "fetch(" not in app
    assert "XMLHttpRequest" not in app
    assert "WebSocket" not in app
    assert "EventSource" not in app
    assert '"POST"' not in app and '"PUT"' not in app and '"DELETE"' not in app
    assert "window.HiyelxStudioFixtures" in app
    assert "const scenarios = [" in fixtures
    assert "schema_version: \"1\"" in fixtures
    assert 'fixtureSelect.addEventListener("change"' in app
    assert "renderScenario(fixtures.getScenario(fixtureSelect.value))" in app
    assert "function renderScenario(scenario)" in app
    assert "renderResources(scenario.snapshot)" in app


def test_all_contract_states_and_safe_user_facing_values_are_fixture_driven() -> None:
    fixtures = (STUDIO / "fixtures.js").read_text()
    expected = {
        "starting",
        "no_session",
        "connecting",
        "fresh",
        "unchanged",
        "stale",
        "unavailable",
        "stopped",
        "unsupported",
        "error",
        "disconnected",
    }
    assert all(f'id: "{state}"' in fixtures for state in expected)
    for text in (
        "angular_position_radians",
        "angular_velocity_radians_per_second",
        "simulation_time_seconds",
        "revision",
        "health_summary",
        "sim_motor",
    ):
        assert text in fixtures


def test_responsive_accessibility_and_stable_refresh_requirements_are_present() -> None:
    html = (STUDIO / "index.html").read_text()
    css = (STUDIO / "studio.css").read_text()
    app = (STUDIO / "app.js").read_text()

    assert 'aria-live="polite"' in html
    assert 'aria-live="off"' in html
    assert ":focus-visible" in css
    assert "prefers-reduced-motion: reduce" in css
    assert "@media (max-width: 319px)" in css
    assert "@media (max-width: 420px)" in css
    assert "grid-template-columns: 1fr" in css
    assert "font-variant-numeric: tabular-nums" in css
    assert "rolling-number" not in app
    assert "count-up" not in app
    assert "aria-label" in app and "aria-describedby" in app


def test_fixture_formatter_is_finite_and_uses_fixed_precision() -> None:
    fixtures = (STUDIO / "fixtures.js").read_text()

    assert "Number.isFinite(value)" in fixtures
    assert "value.toFixed(digits)" in fixtures
    assert 'return "—"' in fixtures


def test_unknown_fixture_uses_sanitized_error_fallback() -> None:
    fixtures = (STUDIO / "fixtures.js").read_text()

    assert "return scenarios.find((scenario) => scenario.id === id)" in fixtures
    assert 'scenarios.find((scenario) => scenario.id === "error")' in fixtures
    assert "|| scenarios[3]" not in fixtures
    assert 'error: "Studio could not read this fixture snapshot."' in fixtures
    assert (
        'return scenarios.find((scenario) => scenario.id === id)\n'
        '      || scenarios.find((scenario) => scenario.id === "error");'
    ) in fixtures


def test_fixture_lookup_behavior_executes_the_real_javascript_module() -> None:
    node = shutil.which("node")
    assert node is not None, "Node.js is required for the fixture lookup regression test"
    script = r"""
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const effects = [];
const context = { fixtureProbeEffects: effects };
context.window = context;
for (const name of ["fetch", "XMLHttpRequest", "WebSocket", "EventSource"]) {
  context[name] = (...args) => effects.push({ name, args });
}
vm.runInNewContext(fs.readFileSync(process.argv[1], "utf8"), context, {
  filename: "studio/fixtures.js",
  timeout: 1000,
});
const api = context.HiyelxStudioFixtures;
assert.ok(api, "fixture module must export its browser global");
const fresh = api.scenarios.find((scenario) => scenario.id === "fresh");
const error = api.scenarios.find((scenario) => scenario.id === "error");
assert.ok(fresh, "fresh fixture must exist");
assert.ok(error, "safe error fixture must exist");
assert.strictEqual(api.getScenario("fresh"), fresh);
assert.notStrictEqual(api.getScenario("fresh"), error);
const before = JSON.stringify(api.scenarios);
const cases = [
  ["unknown", "unknown-fixture"],
  ["empty", ""],
  ["null", null],
  ["undefined", undefined],
  ["invalid-object", {}],
  ["invalid-number", 0],
  ["invalid-boolean", false],
];
for (const [name, id] of cases) {
  const result = api.getScenario(id);
  assert.strictEqual(result, error, `${name} must return the exact error fixture`);
  assert.notStrictEqual(result, fresh, `${name} must never return the fresh fixture`);
}
const unknownResult = api.getScenario("unknown-fixture");
for (const field of ["id", "label", "badge", "message", "freshness"]) {
  assert.equal(typeof unknownResult[field], "string");
  assert.ok(!unknownResult[field].includes("unknown-fixture"));
}
assert.equal(unknownResult.message, "Studio could not read this fixture snapshot.");
assert.equal(JSON.stringify(api.scenarios), before, "fixture lookup must not mutate fixture state");
assert.deepEqual(effects, [], "fixture lookup must not access network APIs");
process.stdout.write(JSON.stringify({
  marker: "studio-fixture-lookup=passed",
  cases: ["fresh", ...cases.map(([name]) => name)],
  side_effects: effects.length,
}));
"""
    def safe_output(value: str | bytes | None) -> str:
        if value is None:
            return ""
        if isinstance(value, bytes):
            value = value.decode("utf-8", errors="replace")
        value = value.replace(str(ROOT), "<repo>").replace(str(Path.home()), "<home>")
        return re.sub(
            r"(?i)\b(token|password|secret|authorization)(\s*[:=]\s*)\S+",
            r"\1\2<redacted>",
            value,
        )

    try:
        result = subprocess.run(
            [node, "-e", script, str((STUDIO / "fixtures.js").resolve())],
            cwd=ROOT,
            shell=False,
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise AssertionError(
            "Node fixture lookup probe timed out (5 seconds); "
            f"stdout={safe_output(exc.stdout)!r}; stderr={safe_output(exc.stderr)!r}"
        ) from None

    failure = (
        f"Node fixture lookup probe failed (exit {result.returncode}); "
        f"stdout={safe_output(result.stdout)!r}; stderr={safe_output(result.stderr)!r}"
    )
    assert result.returncode == 0, failure
    assert result.stderr == "", failure
    assert json.loads(result.stdout) == {
        "marker": "studio-fixture-lookup=passed",
        "cases": [
            "fresh",
            "unknown",
            "empty",
            "null",
            "undefined",
            "invalid-object",
            "invalid-number",
            "invalid-boolean",
        ],
        "side_effects": 0,
    }, failure


def test_initial_fixture_selector_and_render_share_fresh_selection() -> None:
    app = (STUDIO / "app.js").read_text()

    assert 'option.selected = scenario.id === "fresh"' in app
    assert 'renderScenario(fixtures.getScenario(fixtureSelect.value))' in app
    assert 'renderScenario(fixtures.getScenario("fresh"))' not in app


def test_session_fixture_label_is_short_and_still_explained_as_static() -> None:
    html = (STUDIO / "index.html").read_text()

    assert "<option>Demo · sim_motor</option>" in html
    assert "Session selection is not connected in P1" not in html
    assert "No session discovery runs in this prototype." in html
    assert '<select id="session-select" disabled' in html
    assert '<label for="session-select">Session</label>' in html


def test_favicon_is_request_free() -> None:
    html = (STUDIO / "index.html").read_text()

    assert '<link rel="icon" href="data:," />' in html
    assert "favicon.ico" not in html
    assert "http://" not in html and "https://" not in html
