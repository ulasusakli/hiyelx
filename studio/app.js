(function () {
  "use strict";

  const PHASE_VIEW = Object.freeze({
    idle: ["neutral", "Waiting", "Waiting for an observable simulation session."],
    connecting: ["neutral", "Connecting", "Connecting to the selected local session."],
    fresh: ["success", "Live", "A fresh schema-v1 observation is available."],
    unchanged: ["success", "Live · unchanged", "Observation succeeded; the validated snapshot is unchanged."],
    stale: ["warning", "Stale", "The last valid observation is stale while Studio retries."],
    unavailable: ["warning", "Unavailable", "Studio preview is temporarily unavailable."],
    stopped: ["neutral", "Stopped", "The selected session is not running."],
    unsupported: ["error", "Unsupported", "This Studio version cannot read this preview schema."],
    error: ["error", "Error", "Studio could not read this snapshot."],
    disconnected: ["error", "Disconnected", "The local Studio Host is disconnected."],
    paused: ["warning", "Paused", "Observation is paused while this tab is in the background."],
    disposed: ["neutral", "Closed", "Studio observation is closed."],
  });
  const SNAPSHOT_PHASES = new Set(["fresh", "unchanged", "stale", "unavailable", "paused"]);

  const elements = Object.freeze({
    connectionBadge: document.getElementById("connection-badge"),
    connectionLabel: document.getElementById("connection-label"),
    emptyCopy: document.getElementById("empty-copy"),
    emptyState: document.getElementById("empty-state"),
    emptyTitle: document.getElementById("empty-title"),
    freshness: document.getElementById("freshness"),
    resourceCount: document.getElementById("resource-count"),
    resourceGrid: document.getElementById("resource-grid"),
    runtimeState: document.getElementById("runtime-state"),
    sessionSelect: document.getElementById("session-select"),
    snapshotState: document.getElementById("snapshot-state"),
    stateMessage: document.getElementById("state-message"),
    stateMessageText: document.getElementById("state-message-text"),
    statePill: document.getElementById("state-pill"),
  });

  let controller = null;
  let unsubscribe = null;
  let discoveryComplete = false;
  let disposed = false;
  let lastMessageKey = "starting";
  let resourceStructure = "";
  let resourceNodes = [];

  function textNode(tag, className, text) {
    const element = document.createElement(tag);
    if (className) element.className = className;
    element.textContent = text;
    return element;
  }

  function finiteNumber(value, digits) {
    if (typeof value === "number" && Number.isFinite(value)) return value.toFixed(digits);
    return "—";
  }

  function formatAge(value) {
    return typeof value === "number" && Number.isFinite(value) && value >= 0
      ? `${value.toFixed(1)} s since last observation`
      : "Last observation age unavailable";
  }

  function makeMetric(index, key, label, unit, description) {
    const wrapper = document.createElement("div");
    wrapper.className = "metric";
    const output = textNode("span", "metric-value", "—");
    const helpId = `metric-${index}-${key}-help`;
    wrapper.append(textNode("span", "metric-label", label), output, textNode("span", "metric-unit", unit));
    if (description) {
      const help = textNode("span", "sr-only", description);
      help.id = helpId;
      output.setAttribute("aria-describedby", helpId);
      wrapper.append(help);
    }
    return { label, output, root: wrapper, unit };
  }

  function createResourceCard(resource, index) {
    const card = document.createElement("article");
    card.className = "resource-card panel";
    const titleId = `resource-title-${index}`;
    card.setAttribute("aria-labelledby", titleId);

    const header = document.createElement("div");
    header.className = "resource-card-header";
    const identityBlock = document.createElement("div");
    const identity = textNode("h3", "resource-identity", resource.identity);
    identity.id = titleId;
    identityBlock.append(textNode("span", "field-label", "Resource identity"), identity);
    const kind = textNode("span", "kind-pill", resource.kind);
    header.append(identityBlock, kind);

    const status = document.createElement("div");
    status.className = "resource-status-row";
    const lifecycle = textNode("span", "status-pill", resource.lifecycle_state);
    const health = textNode("span", "status-pill health-pill", resource.health_status);
    status.append(
      textNode("span", "field-label", "Lifecycle"),
      lifecycle,
      textNode("span", "field-label", "Health"),
      health,
    );

    const healthSummary = textNode("p", "health-summary", "No health summary reported.");
    const metricsRoot = document.createElement("div");
    metricsRoot.className = "metrics-grid";
    const metrics = {
      position: makeMetric(index, "position", "Position", "rad"),
      revision: makeMetric(
        index,
        "revision",
        "Revision",
        "state mutations",
        "Revision counts successful resource-state mutations. Preview reads do not increment it. Equal revisions do not prove the whole runtime snapshot is unchanged; revision is not physical movement or hardware evidence.",
      ),
      simulationTime: makeMetric(index, "simulation-time", "Simulation time", "simulated s"),
      velocity: makeMetric(index, "velocity", "Velocity", "rad/s"),
    };
    metricsRoot.append(
      metrics.position.root,
      metrics.velocity.root,
      metrics.simulationTime.root,
      metrics.revision.root,
    );
    card.append(header, status, healthSummary, metricsRoot);
    return { card, health, healthSummary, identity, kind, lifecycle, metrics };
  }

  function updateMetric(metric, value) {
    metric.output.textContent = value;
    metric.output.setAttribute("aria-label", `${metric.label}: ${value} ${metric.unit}`);
  }

  function clearResources(title, copy) {
    if (resourceNodes.length > 0 || elements.resourceGrid.children.length > 0) {
      elements.resourceGrid.replaceChildren();
    }
    resourceNodes = [];
    resourceStructure = "";
    elements.resourceGrid.hidden = true;
    elements.emptyState.hidden = false;
    elements.emptyTitle.textContent = title;
    elements.emptyCopy.textContent = copy;
  }

  function renderResources(snapshot) {
    if (!snapshot || snapshot.resources.length === 0) {
      clearResources("No resource snapshot", "Resource values appear after a valid observation is available.");
      return;
    }
    const nextStructure = JSON.stringify(snapshot.resources.map(({ identity, kind }) => [identity, kind]));
    if (nextStructure !== resourceStructure) {
      resourceNodes = snapshot.resources.map(createResourceCard);
      elements.resourceGrid.replaceChildren(...resourceNodes.map(({ card }) => card));
      resourceStructure = nextStructure;
    }
    snapshot.resources.forEach((resource, index) => {
      const nodes = resourceNodes[index];
      nodes.identity.textContent = resource.identity;
      nodes.kind.textContent = resource.kind;
      nodes.lifecycle.textContent = resource.lifecycle_state;
      nodes.health.textContent = resource.health_status;
      nodes.healthSummary.textContent = resource.health_summary || "No health summary reported.";
      updateMetric(nodes.metrics.position, finiteNumber(resource.state.angular_position_radians, 3));
      updateMetric(nodes.metrics.velocity, finiteNumber(resource.state.angular_velocity_radians_per_second, 3));
      updateMetric(nodes.metrics.simulationTime, finiteNumber(resource.state.simulation_time_seconds, 1));
      updateMetric(nodes.metrics.revision, String(resource.state.revision));
    });
    elements.resourceGrid.hidden = false;
    elements.emptyState.hidden = true;
  }

  function viewForState(state) {
    if (state.phase === "idle" && discoveryComplete && state.sessions.length === 0) {
      return ["neutral", "No session", "No observable simulation session is running."];
    }
    return PHASE_VIEW[state.phase] || PHASE_VIEW.error;
  }

  function freshnessForState(state, snapshotVisible) {
    if (state.phase === "fresh") return "Observed now";
    if (state.phase === "unchanged") return "Observed now · unchanged";
    if (state.phase === "stale") return `Stale · ${formatAge(state.snapshotAgeSeconds)}`;
    if (state.phase === "unavailable" && snapshotVisible) {
      return `Unavailable · ${formatAge(state.snapshotAgeSeconds)}`;
    }
    if (state.phase === "paused" && snapshotVisible) return `Paused · ${formatAge(state.snapshotAgeSeconds)}`;
    if (state.phase === "connecting") return "Waiting for first observation";
    if (state.phase === "disposed") return "Observation closed";
    if (state.phase === "idle" && discoveryComplete) return "No session selected";
    return "No current observation";
  }

  function snapshotLabel(state, snapshotVisible) {
    if (state.phase === "fresh") return "Fresh";
    if (state.phase === "unchanged") return "Fresh · unchanged";
    if (state.phase === "stale") return "Stale";
    if (state.phase === "unavailable") return snapshotVisible ? "Stale · unavailable" : "Unavailable";
    if (state.phase === "paused") return snapshotVisible ? "Paused" : "No snapshot";
    if (state.phase === "connecting") return "Loading";
    return "No snapshot";
  }

  function renderState(state) {
    const knownPhase = Object.hasOwn(PHASE_VIEW, state.phase);
    const safeState = knownPhase ? state : { ...state, phase: "error", snapshot: null };
    const [severity, label, message] = viewForState(safeState);
    const snapshotVisible = SNAPSHOT_PHASES.has(safeState.phase) && safeState.snapshot !== null;
    document.body.dataset.phase = safeState.phase;
    elements.connectionBadge.dataset.severity = severity;
    elements.connectionLabel.textContent = label;
    elements.statePill.dataset.severity = severity;
    elements.statePill.textContent = label;
    elements.stateMessage.dataset.severity = severity;
    const messageKey = `${safeState.phase}:${message}`;
    if (messageKey !== lastMessageKey) {
      elements.stateMessageText.textContent = message;
      lastMessageKey = messageKey;
    }
    elements.freshness.textContent = freshnessForState(safeState, snapshotVisible);
    elements.snapshotState.textContent = snapshotLabel(safeState, snapshotVisible);
    elements.runtimeState.textContent = snapshotVisible ? safeState.snapshot.runtime_state : "—";
    elements.resourceCount.textContent = snapshotVisible ? String(safeState.snapshot.resources.length) : "0";
    if (snapshotVisible) {
      renderResources(safeState.snapshot);
    } else {
      clearResources("No resource snapshot", "Resource values appear after a valid observation is available.");
    }
  }

  function renderStartingFailure(error) {
    const code = error && typeof error === "object" && typeof error.code === "string" ? error.code : "";
    let phase = "error";
    if (code === "invalid_capability" || code === "host_disconnected") phase = "disconnected";
    if (code === "schema_unsupported" || code === "preview_unsupported") phase = "unsupported";
    if (code === "sessions_unavailable" || code === "preview_unavailable") phase = "unavailable";
    renderState({
      phase,
      sessions: Object.freeze([]),
      snapshot: null,
      snapshotAgeSeconds: null,
    });
  }

  function populateSessions(sessions) {
    const options = sessions.map((session) => {
      const option = document.createElement("option");
      option.value = session;
      option.textContent = session;
      return option;
    });
    if (options.length === 0) {
      const option = document.createElement("option");
      option.value = "";
      option.textContent = "No observable sessions";
      options.push(option);
    }
    elements.sessionSelect.replaceChildren(...options);
    elements.sessionSelect.disabled = sessions.length === 0;
  }

  function visibilityAdapter() {
    return Object.freeze({
      isVisible: () => document.visibilityState !== "hidden",
      subscribe(listener) {
        document.addEventListener("visibilitychange", listener);
        return () => document.removeEventListener("visibilitychange", listener);
      },
    });
  }

  function dispose() {
    if (disposed) return;
    disposed = true;
    if (controller !== null) controller.dispose();
    if (unsubscribe !== null) unsubscribe();
  }

  elements.sessionSelect.addEventListener("change", () => {
    if (controller === null || disposed) return;
    controller.selectSession(elements.sessionSelect.value || null);
  });
  window.addEventListener("pagehide", dispose);
  window.addEventListener("beforeunload", dispose);

  async function start() {
    try {
      const client = window.HiyelxStudioHostClient;
      if (!client || typeof client.createController !== "function") throw new Error("client unavailable");
      controller = client.createController({
        createAbortController: () => new AbortController(),
        fetch: window.fetch.bind(window),
        history: window.history,
        location: window.location,
        now: () => window.performance.now(),
        setTimer: window.setTimeout.bind(window),
        clearTimer: window.clearTimeout.bind(window),
        visibility: visibilityAdapter(),
      });
      unsubscribe = controller.subscribe(renderState);
      await controller.fetchMetadata();
      const sessions = await controller.refreshSessions();
      if (disposed) return;
      discoveryComplete = true;
      populateSessions(sessions);
      if (sessions.length === 0) {
        renderState(controller.getState());
        return;
      }
      elements.sessionSelect.value = sessions[0];
      controller.selectSession(sessions[0]);
      controller.start();
    } catch (error) {
      dispose();
      elements.sessionSelect.disabled = true;
      renderStartingFailure(error);
    }
  }

  void start();
})();
