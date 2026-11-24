/* Live DOM adapter composing HiyelxStudioHostClient onto studio/live.html. */
(function (root) {
  "use strict";

  function formatNumber(value, digits) {
    if (typeof value !== "number" || !Number.isFinite(value)) return "—";
    return value.toFixed(digits);
  }

  function formatAge(ageSeconds, suffix) {
    if (typeof ageSeconds !== "number" || !Number.isFinite(ageSeconds) || ageSeconds < 0) {
      return suffix || "No live snapshot";
    }
    const base = ageSeconds < 0.5 ? "Updated just now" : `Updated ${ageSeconds.toFixed(1)}s ago`;
    return suffix ? `${base} (${suffix})` : base;
  }

  function textNode(doc, tag, className, text) {
    const element = doc.createElement(tag);
    if (className) element.className = className;
    element.textContent = text;
    return element;
  }

  function makeMetric(doc, label, value, unit, description) {
    const wrapper = doc.createElement("div");
    wrapper.className = "metric";
    const labelId = `metric-${label.toLowerCase().replaceAll(" ", "-")}`;
    wrapper.append(textNode(doc, "span", "metric-label", label));
    const output = textNode(doc, "span", "metric-value", value);
    output.setAttribute("aria-label", `${label}: ${value} ${unit}`);
    wrapper.append(output, textNode(doc, "span", "metric-unit", unit));
    if (description) {
      const help = textNode(doc, "span", "sr-only", description);
      help.id = labelId;
      output.setAttribute("aria-describedby", labelId);
      wrapper.append(help);
    }
    return wrapper;
  }

  function describeLiveState(controllerState, discoveryError) {
    if (discoveryError !== null) {
      if (discoveryError === "invalid_capability" || discoveryError === "request_rejected") {
        return {
          badge: "Access rejected",
          emptyCopy: "Restart Studio from the CLI so a fresh local capability token is issued.",
          emptyTitle: "Session access rejected",
          freshness: "Authorization rejected",
          message: "Session access key is missing, invalid, or expired. Launch Studio again with hiyelx studio.",
          severity: "error",
          snapshotState: "Rejected",
        };
      }
      if (discoveryError === "schema_unsupported" || discoveryError === "preview_unsupported") {
        return {
          badge: "Schema unsupported",
          emptyCopy: "This Studio build refuses unknown or incompatible Runtime schema versions.",
          emptyTitle: "Unsupported schema version",
          freshness: "Schema rejected",
          message: "This Studio version cannot read the schema returned by the local Host.",
          severity: "error",
          snapshotState: "Unsupported",
        };
      }
      if (discoveryError === "host_disconnected") {
        return {
          badge: "Host disconnected",
          emptyCopy: "Verify that hiyelx studio is still running in your terminal.",
          emptyTitle: "Studio Host unavailable",
          freshness: "Host unreachable",
          message: "Connection to the local Studio Host was lost.",
          severity: "error",
          snapshotState: "Disconnected",
        };
      }
      return {
        badge: "Unavailable",
        emptyCopy: "Try refreshing local sessions after the Runtime finishes starting or stopping.",
        emptyTitle: "Sessions unavailable",
        freshness: "Discovery unavailable",
        message: "Studio could not read local sessions from the Runtime host.",
        severity: "error",
        snapshotState: "Unavailable",
      };
    }

    const phase = controllerState.phase;
    const error = controllerState.error;
    const hasSnapshot = controllerState.snapshot !== null;
    const age = controllerState.snapshotAgeSeconds;

    if (phase === "fresh") {
      return {
        badge: "Live · Connected",
        emptyCopy: "",
        emptyTitle: "",
        freshness: formatAge(age, ""),
        message: `Observing live session "${controllerState.selectedSession}" (read-only).`,
        severity: "success",
        snapshotState: "Live data",
      };
    }
    if (phase === "unchanged") {
      return {
        badge: "Live · Connected",
        emptyCopy: "",
        emptyTitle: "",
        freshness: formatAge(age, "unchanged"),
        message: `Observing live session "${controllerState.selectedSession}" (snapshot unchanged).`,
        severity: "success",
        snapshotState: "Live data",
      };
    }
    if (phase === "stale") {
      return {
        badge: "Stale snapshot",
        emptyCopy: "",
        emptyTitle: "",
        freshness: formatAge(age, "stale"),
        message: `Latest refresh failed (${controllerState.consecutiveFailures}); retaining last verified snapshot.`,
        severity: "warning",
        snapshotState: "Stale",
      };
    }
    if (phase === "paused") {
      return {
        badge: "Paused",
        emptyCopy: "Return focus to this tab to resume read-only polling.",
        emptyTitle: "Observation paused",
        freshness: hasSnapshot ? formatAge(age, "paused") : "Paused",
        message: "Observation is paused while this view is hidden.",
        severity: "neutral",
        snapshotState: hasSnapshot ? "Paused" : "No snapshot",
      };
    }
    if (phase === "stopped") {
      return {
        badge: "Session stopped",
        emptyCopy: "Start a local Runtime session or refresh the session list.",
        emptyTitle: "Selected session stopped",
        freshness: "Session ended",
        message: `Session "${controllerState.selectedSession}" is no longer running.`,
        severity: "warning",
        snapshotState: "Stopped",
      };
    }
    if (phase === "unsupported") {
      return {
        badge: "Schema unsupported",
        emptyCopy: "This Studio version cannot read the preview schema from the Runtime.",
        emptyTitle: "Unsupported preview schema",
        freshness: "Schema rejected",
        message: "This Studio version cannot read this preview schema.",
        severity: "error",
        snapshotState: "Unsupported",
      };
    }
    if (phase === "disconnected") {
      return {
        badge: "Host disconnected",
        emptyCopy: "Verify that hiyelx studio is still running locally.",
        emptyTitle: "Local Host disconnected",
        freshness: "Host unreachable",
        message: "Connection to the local Studio Host was lost.",
        severity: "error",
        snapshotState: "Disconnected",
      };
    }
    if (phase === "unavailable") {
      return {
        badge: "Unavailable",
        emptyCopy: "Preview reads failed repeatedly. Refresh sessions or check the Runtime owner.",
        emptyTitle: "Preview unavailable",
        freshness: hasSnapshot ? formatAge(age, "unavailable") : "Preview unavailable",
        message: "Studio preview is temporarily unavailable.",
        severity: "error",
        snapshotState: "Unavailable",
      };
    }
    if (phase === "error") {
      if (error === "request_rejected") {
        return {
          badge: "Access rejected",
          emptyCopy: "Restart Studio from the CLI to obtain a valid session capability.",
          emptyTitle: "Access rejected",
          freshness: "Authorization rejected",
          message: "Studio request was rejected by the local Host.",
          severity: "error",
          snapshotState: "Rejected",
        };
      }
      return {
        badge: "Read error",
        emptyCopy: "Check the local Runtime session and refresh.",
        emptyTitle: "Snapshot read failed",
        freshness: "Read error",
        message: "Studio could not read this snapshot.",
        severity: "error",
        snapshotState: "Error",
      };
    }
    if (phase === "connecting") {
      return {
        badge: "Connecting",
        emptyCopy: "Waiting for the first validated snapshot from the selected Runtime session.",
        emptyTitle: "Connecting to session",
        freshness: "Fetching snapshot…",
        message: `Connecting to local Runtime session "${controllerState.selectedSession}".`,
        severity: "neutral",
        snapshotState: "Connecting",
      };
    }
    if (controllerState.sessions.length === 0) {
      return {
        badge: "No active session",
        emptyCopy: "Start a local runtime session with hiyelx runtime start, then click Refresh sessions.",
        emptyTitle: "No active local session",
        freshness: "No session selected",
        message: "No running local Runtime session was found.",
        severity: "neutral",
        snapshotState: "No snapshot",
      };
    }
    return {
      badge: "Ready",
      emptyCopy: "Choose an observable session to begin live read-only polling.",
      emptyTitle: "Select a session",
      freshness: "Idle",
      message: "Select an observable local Runtime session.",
      severity: "neutral",
      snapshotState: "No snapshot",
    };
  }

  function mountLiveStudio(deps) {
    const doc = deps.document;
    const hostClient = deps.hostClient;
    const connectionBadge = doc.getElementById("connection-badge");
    const connectionLabel = doc.getElementById("connection-label");
    const statePill = doc.getElementById("state-pill");
    const stateMessage = doc.getElementById("state-message");
    const stateMessageText = doc.getElementById("state-message-text");
    const freshnessEl = doc.getElementById("freshness");
    const runtimeStateEl = doc.getElementById("runtime-state");
    const resourceCountEl = doc.getElementById("resource-count");
    const snapshotStateEl = doc.getElementById("snapshot-state");
    const hostVersionTag = doc.getElementById("host-version-tag");
    const sessionSelect = doc.getElementById("session-select");
    const refreshButton = doc.getElementById("refresh-sessions-button");
    const resourceGrid = doc.getElementById("resource-grid");
    const emptyState = doc.getElementById("empty-state");
    const emptyTitle = doc.getElementById("empty-title");
    const emptyCopy = doc.getElementById("empty-copy");
    const runtimePackageSummary = doc.getElementById("runtime-package-summary");
    const runtimeModelsGrid = doc.getElementById("runtime-models-grid");

    let controller = null;
    let discoveryError = null;
    let runtimeInfo = null;
    let disposed = false;

    function renderRuntimeInfo(info, cleared) {
      if (runtimePackageSummary === null || runtimeModelsGrid === null) return;
      runtimeModelsGrid.replaceChildren();
      if (cleared || info === null) {
        runtimePackageSummary.textContent = cleared
          ? "Runtime capability metadata unavailable."
          : "Discovering installed package…";
        return;
      }
      runtimePackageSummary.textContent = `hiyelx ${info.package_version} · Config schemas: ${info.supported_config_schemas.map((s) => `v${s}`).join(", ")} · ${info.registered_models.length} built-in models`;
      info.registered_models.forEach((entry, index) => {
        const card = doc.createElement("article");
        card.className = "resource-card panel";
        card.setAttribute("aria-labelledby", `runtime-model-title-${index}`);

        const header = doc.createElement("div");
        header.className = "resource-card-header";
        const title = textNode(doc, "h3", "resource-identity", entry.model);
        title.id = `runtime-model-title-${index}`;
        header.append(title, textNode(doc, "span", "kind-pill", entry.category));
        card.append(header);

        const capRow = doc.createElement("div");
        capRow.className = "resource-status-row";
        entry.capabilities.forEach((capabilityName) => {
          capRow.append(textNode(doc, "span", "status-pill", capabilityName));
        });
        card.append(capRow);
        runtimeModelsGrid.append(card);
      });
    }

    function renderResources(snapshot, emptyHeadline, emptyDescription) {
      resourceGrid.replaceChildren();
      if (!snapshot || snapshot.resources.length === 0) {
        resourceGrid.hidden = true;
        emptyState.hidden = false;
        if (emptyHeadline) emptyTitle.textContent = emptyHeadline;
        if (emptyDescription) emptyCopy.textContent = emptyDescription;
        return;
      }

      resourceGrid.hidden = false;
      emptyState.hidden = true;
      snapshot.resources.forEach((resource, index) => {
        const card = doc.createElement("article");
        card.className = "resource-card panel";
        card.setAttribute("aria-labelledby", `resource-title-${index}`);

        const cardHeader = doc.createElement("div");
        cardHeader.className = "resource-card-header";
        const identityBlock = doc.createElement("div");
        const title = textNode(doc, "h3", "resource-identity", resource.identity);
        title.id = `resource-title-${index}`;
        identityBlock.append(
          textNode(doc, "span", "field-label", "Resource identity"),
          title,
        );
        cardHeader.append(identityBlock, textNode(doc, "span", "kind-pill", resource.kind));
        card.append(cardHeader);

        const lifecycle = doc.createElement("div");
        lifecycle.className = "resource-status-row";
        lifecycle.append(
          textNode(doc, "span", "field-label", "Lifecycle"),
          textNode(doc, "span", "status-pill", resource.lifecycle_state),
          textNode(doc, "span", "field-label", "Health"),
          textNode(doc, "span", "status-pill health-pill", resource.health_status),
        );
        card.append(lifecycle);
        card.append(
          textNode(
            doc,
            "p",
            "health-summary",
            resource.health_summary || "No health summary reported.",
          ),
        );

        const metrics = doc.createElement("div");
        metrics.className = "metrics-grid";
        metrics.append(
          makeMetric(doc, "Position", formatNumber(resource.state.angular_position_radians, 3), "rad"),
          makeMetric(doc, "Velocity", formatNumber(resource.state.angular_velocity_radians_per_second, 3), "rad/s"),
          makeMetric(doc, "Simulation time", formatNumber(resource.state.simulation_time_seconds, 1), "simulated s"),
          makeMetric(
            doc,
            "Revision",
            String(resource.state.revision),
            "state mutations",
            "Revision counts successful resource-state mutations. Preview reads do not increment it.",
          ),
        );
        card.append(metrics);
        resourceGrid.append(card);
      });
    }

    function renderSessionOptions(sessions, selectedSession, locked) {
      sessionSelect.replaceChildren();
      if (locked || sessions.length === 0) {
        const option = doc.createElement("option");
        option.value = "";
        option.textContent = locked ? "Host access unavailable" : "No observable local sessions";
        option.selected = true;
        sessionSelect.append(option);
        sessionSelect.disabled = true;
        return;
      }
      sessionSelect.disabled = false;
      sessions.forEach((sessionId) => {
        const option = doc.createElement("option");
        option.value = sessionId;
        option.textContent = sessionId;
        option.selected = sessionId === selectedSession;
        sessionSelect.append(option);
      });
    }

    function render(controllerState) {
      const presentation = describeLiveState(controllerState, discoveryError);
      const authLocked = discoveryError === "invalid_capability"
        || discoveryError === "request_rejected"
        || discoveryError === "host_disconnected"
        || controllerState.phase === "disconnected"
        || (controllerState.phase === "error" && controllerState.error === "request_rejected");

      connectionBadge.dataset.severity = presentation.severity;
      connectionLabel.textContent = presentation.badge;
      statePill.dataset.severity = presentation.severity;
      statePill.textContent = presentation.badge;
      stateMessage.dataset.severity = presentation.severity;
      stateMessageText.textContent = presentation.message;
      freshnessEl.textContent = presentation.freshness;
      snapshotStateEl.textContent = presentation.snapshotState;

      const visibleSnapshot = discoveryError === null
        && controllerState.phase !== "unavailable"
        ? controllerState.snapshot
        : null;
      runtimeStateEl.textContent = visibleSnapshot ? visibleSnapshot.runtime_state : "—";
      resourceCountEl.textContent = visibleSnapshot ? String(visibleSnapshot.resources.length) : "0";
      renderResources(visibleSnapshot, presentation.emptyTitle, presentation.emptyCopy);
      renderRuntimeInfo(runtimeInfo, authLocked || discoveryError === "schema_unsupported");
      renderSessionOptions(controllerState.sessions, controllerState.selectedSession, authLocked);
      refreshButton.disabled = discoveryError === "invalid_capability"
        || discoveryError === "request_rejected";
    }

    const emptyControllerState = Object.freeze({
      consecutiveFailures: 0,
      error: null,
      generation: 0,
      observing: false,
      phase: "idle",
      selectedSession: null,
      sessions: Object.freeze([]),
      snapshot: null,
      snapshotAgeSeconds: null,
      visible: true,
    });

    try {
      controller = hostClient.createController({
        createAbortController: deps.createAbortController,
        fetch: deps.fetch,
        history: deps.history,
        location: deps.location,
        now: deps.now,
        setTimer: deps.setTimer,
        clearTimer: deps.clearTimer,
        visibility: deps.visibility,
      });
    } catch (error) {
      discoveryError = error && typeof error.code === "string"
        ? error.code : "invalid_capability";
      render(emptyControllerState);
      return Object.freeze({
        dispose: () => { disposed = true; },
        refresh: async () => undefined,
      });
    }

    const unsubscribe = controller.subscribe(render);

    async function refresh() {
      if (disposed || controller === null) return;
      discoveryError = null;
      try {
        const meta = await controller.fetchMetadata();
        if (disposed) return;
        hostVersionTag.textContent = `HIYELX ${meta.app_version} · HOST v${meta.host_version}`;
        if (typeof controller.fetchRuntimeInfo === "function") {
          runtimeInfo = await controller.fetchRuntimeInfo();
          if (disposed) return;
        }
        const discovered = await controller.refreshSessions();
        if (disposed) return;
        const current = controller.getState().selectedSession;
        if (discovered.length === 0) {
          controller.selectSession(null);
          render(controller.getState());
          return;
        }
        if (current === null || !discovered.includes(current)) {
          controller.selectSession(discovered[0]);
        }
        controller.start();
      } catch (error) {
        if (disposed) return;
        discoveryError = error && typeof error.code === "string"
          ? error.code : "sessions_unavailable";
        render(controller.getState());
      }
    }

    function onSessionChange() {
      if (disposed || controller === null) return;
      const next = sessionSelect.value || null;
      discoveryError = null;
      controller.selectSession(next);
      if (next !== null) controller.start();
    }

    function onRefreshClick() {
      void refresh();
    }

    sessionSelect.addEventListener("change", onSessionChange);
    refreshButton.addEventListener("click", onRefreshClick);
    const bootstrapPromise = refresh();

    function dispose() {
      if (disposed) return;
      disposed = true;
      sessionSelect.removeEventListener("change", onSessionChange);
      refreshButton.removeEventListener("click", onRefreshClick);
      unsubscribe();
      if (controller !== null) controller.dispose();
    }

    return Object.freeze({
      bootstrapPromise,
      controller,
      dispose,
      refresh,
    });
  }

  root.HiyelxStudioLiveApp = Object.freeze({
    describeLiveState,
    mountLiveStudio,
  });

  if (typeof root.document !== "undefined"
    && root.document !== null
    && typeof root.document.getElementById === "function"
    && root.HiyelxStudioHostClient
    && root.document.getElementById("session-select") !== null) {
    mountLiveStudio({
      clearTimer: (id) => root.clearTimeout(id),
      createAbortController: () => new root.AbortController(),
      document: root.document,
      fetch: (url, init) => root.fetch(url, init),
      history: root.history,
      hostClient: root.HiyelxStudioHostClient,
      location: root.location,
      now: () => root.performance.now(),
      setTimer: (fn, delay) => root.setTimeout(fn, delay),
      visibility: {
        isVisible: () => root.document.visibilityState !== "hidden",
        subscribe: (listener) => {
          root.document.addEventListener("visibilitychange", listener);
          return () => root.document.removeEventListener("visibilitychange", listener);
        },
      },
    });
  }
})(globalThis);
