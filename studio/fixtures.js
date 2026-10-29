/* Static, non-sensitive examples for the STUDIO-P1 shell. No runtime access. */
(function (root) {
  "use strict";

  const snapshot = {
    schema_version: "1",
    runtime_state: "running",
    resources: [
      {
        identity: "sim_motor",
        kind: "motor",
        lifecycle_state: "running",
        health_status: "healthy",
        health_summary: null,
        state: {
          angular_position_radians: 0.42,
          angular_velocity_radians_per_second: 0.18,
          simulation_time_seconds: 12.4,
          revision: 3,
        },
      },
    ],
  };

  const messages = {
    starting: "Studio Lite is starting. Fixture preview only; no host is connected.",
    no_session: "No observable local session is available in this fixture.",
    connecting: "Connecting to the selected session is not implemented in P1.",
    fresh: "Connected fixture. Simulation snapshot is current.",
    unchanged: "Connected fixture. Snapshot contents are unchanged.",
    stale: "The latest fixture refresh failed. Showing the last known values as stale.",
    unavailable: "This fixture session is unavailable. Its last snapshot is not current.",
    stopped: "The selected fixture session is not running.",
    unsupported: "This Studio version cannot read the fixture preview schema.",
    error: "Studio could not read this fixture snapshot.",
    disconnected: "The local Studio host is disconnected in this fixture.",
  };

  const scenarios = [
    { id: "starting", label: "App starting", severity: "neutral", badge: "Starting", snapshot: null, freshness: "Not available" },
    { id: "no_session", label: "No local session", severity: "neutral", badge: "No session", snapshot: null, freshness: "Not available" },
    { id: "connecting", label: "Session selected / connecting", severity: "neutral", badge: "Connecting", snapshot: null, freshness: "Waiting for snapshot" },
    { id: "fresh", label: "Connected / fresh snapshot", severity: "success", badge: "Connected · fresh", snapshot, freshness: "Just now · fixture" },
    { id: "unchanged", label: "Connected / unchanged snapshot", severity: "success", badge: "Connected · unchanged", snapshot, freshness: "Just now · fixture" },
    { id: "stale", label: "Stale snapshot", severity: "warning", badge: "Stale", snapshot, freshness: "Last known · fixture" },
    { id: "unavailable", label: "Session unavailable", severity: "warning", badge: "Unavailable", snapshot, freshness: "Last known · fixture" },
    { id: "stopped", label: "Runtime stopped", severity: "neutral", badge: "Stopped", snapshot: null, freshness: "Not available" },
    { id: "unsupported", label: "Schema unsupported", severity: "error", badge: "Unsupported", snapshot: null, freshness: "Not available" },
    { id: "error", label: "Sanitized application error", severity: "error", badge: "Read error", snapshot: null, freshness: "Not available" },
    { id: "disconnected", label: "Host disconnected", severity: "error", badge: "Disconnected", snapshot: null, freshness: "Not available" },
  ].map((scenario) => Object.freeze({
    ...scenario,
    message: messages[scenario.id],
  }));

  function getScenario(id) {
    return scenarios.find((scenario) => scenario.id === id)
      || scenarios.find((scenario) => scenario.id === "error");
  }

  function formatNumber(value, digits) {
    if (typeof value !== "number" || !Number.isFinite(value)) return "—";
    return value.toFixed(digits);
  }

  root.HiyelxStudioFixtures = Object.freeze({
    scenarios: Object.freeze(scenarios),
    getScenario,
    formatNumber,
  });
})(window);
