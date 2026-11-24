/* Read-only, DOM-independent transport for the local HIYELX Studio Host. */
(function (root) {
  "use strict";

  const CAPABILITY_HEADER = "X-HIYELX-Studio-Capability";
  const POLL_INTERVAL_MS = 1000;
  const CAPABILITY_PATTERN = /^[A-Za-z0-9_-]{43}$/;
  const SESSION_PATTERN = /^[a-z0-9][a-z0-9_-]{0,47}$/;
  const LOOPBACK_ORIGIN_PATTERN = /^http:\/\/127\.0\.0\.1:([0-9]{1,5})$/;
  const RUNTIME_STATES = new Set([
    "new", "starting", "running", "stopping", "stopped", "failed",
  ]);
  const LIFECYCLE_STATES = new Set([
    "created", "starting", "running", "stopping", "stopped", "failed",
  ]);
  const HEALTH_STATUSES = new Set([
    "unknown", "healthy", "degraded", "unhealthy",
  ]);
  const HEALTH_SUMMARIES = new Set(
    [
      "deadline exceeded",
      "backend unavailable",
      "safe-stop failed",
      "lifecycle cleanup failed",
    ].flatMap((prefix) => [
      "startup",
      "shutdown",
      "motor command",
      "motor state read",
      "safe-stop",
    ].map((operation) => `${prefix} during ${operation}`)),
  );
  const ERROR_RESPONSES = Object.freeze({
    invalid_request: [400, "Studio request is invalid."],
    request_rejected: [403, "Studio request was rejected."],
    not_found: [404, "Studio resource was not found."],
    session_not_running: [404, "The selected session is not running."],
    method_not_allowed: [405, "Studio request method is not allowed."],
    request_too_large: [413, "Studio request is too large."],
    host_rejected: [421, "Studio request was rejected."],
    preview_unsupported: [422, "This Studio version cannot read this preview schema."],
    application_error: [500, "Studio could not read this snapshot."],
    sessions_unavailable: [503, "Studio could not list local sessions."],
    preview_unavailable: [503, "Studio preview is temporarily unavailable."],
  });

  class StudioClientError extends Error {
    constructor(code) {
      super("Studio client operation failed.");
      this.name = "StudioClientError";
      this.code = code;
    }
  }

  function isObject(value) {
    return value !== null && typeof value === "object" && !Array.isArray(value);
  }

  function hasExactKeys(value, expected) {
    if (!isObject(value)) return false;
    const actual = Object.keys(value).sort();
    const wanted = [...expected].sort();
    return actual.length === wanted.length
      && actual.every((key, index) => key === wanted[index]);
  }

  function freezeDeep(value) {
    if (value !== null && typeof value === "object" && !Object.isFrozen(value)) {
      Object.values(value).forEach(freezeDeep);
      Object.freeze(value);
    }
    return value;
  }

  function validLoopbackOrigin(origin) {
    if (typeof origin !== "string") return false;
    const match = LOOPBACK_ORIGIN_PATTERN.exec(origin);
    if (match === null) return false;
    const port = Number(match[1]);
    return Number.isInteger(port) && port >= 1 && port <= 65535;
  }

  function consumeCapability(location, history) {
    if (!isObject(location) || !isObject(history)
      || typeof history.replaceState !== "function"
      || !validLoopbackOrigin(location.origin)
      || typeof location.hash !== "string"
      || typeof location.pathname !== "string"
      || typeof location.search !== "string") {
      throw new StudioClientError("invalid_capability");
    }
    const fragment = location.hash;
    const replacement = `${location.pathname}${location.search}`;
    try {
      history.replaceState(history.state ?? null, "", replacement || "/");
    } catch (_error) {
      throw new StudioClientError("invalid_capability");
    }
    const match = /^#capability=([A-Za-z0-9_-]{43})$/.exec(fragment);
    if (match === null || !CAPABILITY_PATTERN.test(match[1])) {
      throw new StudioClientError("invalid_capability");
    }
    return match[1];
  }

  function validateMetadata(value) {
    if (!hasExactKeys(value, [
      "app_version", "host_version", "ready", "schema_version",
    ])
      || typeof value.app_version !== "string"
      || value.app_version.length === 0
      || value.host_version !== "1"
      || value.ready !== true
      || value.schema_version !== "1") {
      throw new StudioClientError(
        isObject(value) && value.schema_version !== "1"
          ? "schema_unsupported" : "invalid_response",
      );
    }
    return freezeDeep({
      app_version: value.app_version,
      host_version: value.host_version,
      ready: value.ready,
      schema_version: value.schema_version,
    });
  }

  function validateRuntimeInfo(value) {
    if (!hasExactKeys(value, [
      "package_version",
      "registered_models",
      "schema_version",
      "supported_config_schemas",
    ])) {
      throw new StudioClientError("invalid_response");
    }
    if (value.schema_version !== "1") {
      throw new StudioClientError("schema_unsupported");
    }
    if (typeof value.package_version !== "string"
      || value.package_version.trim().length === 0
      || !Array.isArray(value.supported_config_schemas)
      || value.supported_config_schemas.length === 0
      || value.supported_config_schemas.some(
        (item) => typeof item !== "string" || item.trim().length === 0,
      )
      || !Array.isArray(value.registered_models)
      || value.registered_models.length > 64) {
      throw new StudioClientError("invalid_response");
    }
    const seen = new Set();
    const models = value.registered_models.map((item) => {
      if (!hasExactKeys(item, ["capabilities", "category", "model"])
        || typeof item.model !== "string"
        || item.model.trim().length === 0
        || seen.has(item.model)
        || typeof item.category !== "string"
        || item.category.trim().length === 0
        || !Array.isArray(item.capabilities)
        || item.capabilities.some(
          (cap) => typeof cap !== "string" || cap.trim().length === 0,
        )) {
        throw new StudioClientError("invalid_response");
      }
      seen.add(item.model);
      return {
        capabilities: [...item.capabilities],
        category: item.category,
        model: item.model,
      };
    });
    return freezeDeep({
      package_version: value.package_version,
      registered_models: models,
      schema_version: value.schema_version,
      supported_config_schemas: [...value.supported_config_schemas],
    });
  }

  function validateSessions(value) {
    if (!hasExactKeys(value, ["schema_version", "sessions"])) {
      throw new StudioClientError("invalid_response");
    }
    if (value.schema_version !== "1") {
      throw new StudioClientError("schema_unsupported");
    }
    if (!Array.isArray(value.sessions) || value.sessions.length > 64) {
      throw new StudioClientError("invalid_response");
    }
    const sessions = value.sessions.map((session) => {
      if (typeof session !== "string" || !SESSION_PATTERN.test(session)) {
        throw new StudioClientError("invalid_response");
      }
      return session;
    });
    if (sessions.some((session, index) => index > 0 && sessions[index - 1] >= session)) {
      throw new StudioClientError("invalid_response");
    }
    return Object.freeze(sessions);
  }

  function validatePreview(value) {
    if (!hasExactKeys(value, ["resources", "runtime_state", "schema_version"])) {
      throw new StudioClientError("invalid_response");
    }
    if (value.schema_version !== "1") {
      throw new StudioClientError("schema_unsupported");
    }
    if (!RUNTIME_STATES.has(value.runtime_state)
      || !Array.isArray(value.resources)
      || value.resources.length !== 1) {
      throw new StudioClientError("invalid_response");
    }
    const identities = new Set();
    const resources = value.resources.map((resource) => {
      if (!hasExactKeys(resource, [
        "health_status",
        "health_summary",
        "identity",
        "kind",
        "lifecycle_state",
        "state",
      ])
        || typeof resource.identity !== "string"
        || resource.identity.length === 0
        || resource.identity.trim().length === 0
        || identities.has(resource.identity)
        || resource.kind !== "motor"
        || !LIFECYCLE_STATES.has(resource.lifecycle_state)
        || !HEALTH_STATUSES.has(resource.health_status)
        || (resource.health_summary !== null
          && !HEALTH_SUMMARIES.has(resource.health_summary))) {
        throw new StudioClientError("invalid_response");
      }
      identities.add(resource.identity);
      if (!hasExactKeys(resource.state, [
        "angular_position_radians",
        "angular_velocity_radians_per_second",
        "revision",
        "simulation_time_seconds",
      ])) {
        throw new StudioClientError("invalid_response");
      }
      const state = resource.state;
      if (typeof state.angular_position_radians !== "number"
        || !Number.isFinite(state.angular_position_radians)
        || typeof state.angular_velocity_radians_per_second !== "number"
        || !Number.isFinite(state.angular_velocity_radians_per_second)
        || typeof state.simulation_time_seconds !== "number"
        || !Number.isFinite(state.simulation_time_seconds)
        || state.simulation_time_seconds < 0
        || !Number.isInteger(state.revision)
        || state.revision < 0) {
        throw new StudioClientError("invalid_response");
      }
      return {
        health_status: resource.health_status,
        health_summary: resource.health_summary,
        identity: resource.identity,
        kind: resource.kind,
        lifecycle_state: resource.lifecycle_state,
        state: {
          angular_position_radians: state.angular_position_radians,
          angular_velocity_radians_per_second: state.angular_velocity_radians_per_second,
          revision: state.revision,
          simulation_time_seconds: state.simulation_time_seconds,
        },
      };
    });
    return freezeDeep({
      resources,
      runtime_state: value.runtime_state,
      schema_version: value.schema_version,
    });
  }

  function validateErrorResponse(value, status) {
    if (!hasExactKeys(value, ["error", "schema_version"])
      || value.schema_version !== "1"
      || !hasExactKeys(value.error, ["code", "message"])
      || typeof value.error.code !== "string"
      || typeof value.error.message !== "string") {
      return new StudioClientError("invalid_response");
    }
    const expected = ERROR_RESPONSES[value.error.code];
    if (expected === undefined
      || expected[0] !== status
      || expected[1] !== value.error.message) {
      return new StudioClientError("invalid_response");
    }
    return new StudioClientError(value.error.code);
  }

  function createController(options) {
    if (!isObject(options)) throw new StudioClientError("invalid_configuration");
    const capability = consumeCapability(options.location, options.history);
    const fetchFn = options.fetch;
    const nowFn = options.now;
    const setTimer = options.setTimer;
    const clearTimer = options.clearTimer;
    const visibility = options.visibility;
    const createAbortController = options.createAbortController;
    if (typeof fetchFn !== "function"
      || typeof nowFn !== "function"
      || typeof setTimer !== "function"
      || typeof clearTimer !== "function"
      || !isObject(visibility)
      || typeof visibility.isVisible !== "function"
      || typeof visibility.subscribe !== "function"
      || typeof createAbortController !== "function") {
      throw new StudioClientError("invalid_configuration");
    }

    function newAbortController() {
      let value;
      try {
        value = createAbortController();
      } catch (_error) {
        throw new StudioClientError("invalid_configuration");
      }
      if (!isObject(value)
        || typeof value.abort !== "function"
        || !isObject(value.signal)
        || typeof value.signal.aborted !== "boolean") {
        throw new StudioClientError("invalid_configuration");
      }
      return value;
    }

    let lastClock = 0;
    function monotonicNow() {
      const candidate = nowFn();
      if (typeof candidate !== "number" || !Number.isFinite(candidate) || candidate < 0) {
        throw new StudioClientError("invalid_clock");
      }
      lastClock = Math.max(lastClock, candidate);
      return lastClock;
    }

    const initialVisible = visibility.isVisible();
    if (typeof initialVisible !== "boolean") {
      throw new StudioClientError("invalid_configuration");
    }

    const listeners = new Set();
    const auxiliaryRequests = new Set();
    let phase = "idle";
    let selectedSession = null;
    let sessions = Object.freeze([]);
    let snapshot = null;
    let snapshotKey = null;
    let lastSuccessfulAt = null;
    let consecutiveFailures = 0;
    let error = null;
    let generation = 0;
    let requestEpoch = 0;
    let observing = false;
    let visible = initialVisible;
    let disposed = false;
    let timer = null;
    let previewRequest = null;
    let immediatePollPending = false;

    function state() {
      const snapshotAgeSeconds = lastSuccessfulAt === null
        ? null : (monotonicNow() - lastSuccessfulAt) / 1000;
      return freezeDeep({
        consecutiveFailures,
        error,
        generation,
        observing,
        phase,
        selectedSession,
        sessions,
        snapshot,
        snapshotAgeSeconds,
        visible,
      });
    }

    function emit() {
      const current = state();
      [...listeners].forEach((listener) => {
        try {
          listener(current);
        } catch (_error) {
          // A future UI consumer cannot alter controller state by throwing.
        }
      });
    }

    function clearScheduledPoll() {
      if (timer !== null) {
        clearTimer(timer);
        timer = null;
      }
    }

    function abortPreview() {
      if (previewRequest !== null) previewRequest.abortController.abort();
    }

    function shouldPoll() {
      return !disposed && observing && visible && selectedSession !== null
        && phase !== "unsupported" && phase !== "stopped";
    }

    function schedulePoll(delay) {
      if (!shouldPoll() || timer !== null) return;
      if (previewRequest !== null) {
        if (delay === 0) immediatePollPending = true;
        return;
      }
      immediatePollPending = false;
      timer = setTimer(() => {
        timer = null;
        void poll();
      }, delay);
    }

    async function fetchJson(path, validator, signal) {
      let response;
      try {
        response = await fetchFn(path, {
          cache: "no-store",
          credentials: "omit",
          headers: Object.freeze({ [CAPABILITY_HEADER]: capability }),
          method: "GET",
          redirect: "error",
          referrerPolicy: "no-referrer",
          signal,
        });
      } catch (_error) {
        if (signal.aborted) throw new StudioClientError("cancelled");
        throw new StudioClientError("host_disconnected");
      }
      if (!isObject(response)
        || !Number.isInteger(response.status)
        || typeof response.ok !== "boolean"
        || typeof response.json !== "function"
        || typeof response.url !== "string") {
        throw new StudioClientError("invalid_response");
      }
      let responseUrl;
      try {
        responseUrl = new URL(response.url, options.location.origin);
      } catch (_error) {
        throw new StudioClientError("invalid_response");
      }
      if (responseUrl.origin !== options.location.origin) {
        throw new StudioClientError("invalid_response");
      }
      let document;
      try {
        document = await response.json();
      } catch (_error) {
        throw new StudioClientError("invalid_response");
      }
      if (response.status === 200 && response.ok) return validator(document);
      throw validateErrorResponse(document, response.status);
    }

    async function auxiliary(path, validator) {
      if (disposed) throw new StudioClientError("disposed");
      const abortController = newAbortController();
      const epoch = requestEpoch;
      auxiliaryRequests.add(abortController);
      try {
        const result = await fetchJson(path, validator, abortController.signal);
        if (disposed || epoch !== requestEpoch) {
          throw new StudioClientError("cancelled");
        }
        return result;
      } finally {
        auxiliaryRequests.delete(abortController);
      }
    }

    function applyFailure(failure) {
      const code = failure instanceof StudioClientError
        ? failure.code : "application_error";
      if (code === "cancelled") return;
      if (code === "preview_unsupported" || code === "schema_unsupported") {
        phase = "unsupported";
        snapshot = null;
        snapshotKey = null;
        lastSuccessfulAt = null;
        error = "preview_unsupported";
        consecutiveFailures += 1;
        emit();
        return;
      }
      if (code === "session_not_running") {
        phase = "stopped";
        snapshot = null;
        snapshotKey = null;
        lastSuccessfulAt = null;
        error = "session_not_running";
        consecutiveFailures += 1;
        emit();
        return;
      }
      consecutiveFailures += 1;
      error = code;
      if (snapshot !== null) {
        phase = consecutiveFailures >= 3 ? "unavailable" : "stale";
      } else if (code === "host_disconnected") {
        phase = "disconnected";
      } else if (code === "preview_unavailable" || code === "not_found") {
        phase = "unavailable";
      } else {
        phase = "error";
      }
      emit();
    }

    async function poll() {
      if (!shouldPoll() || previewRequest !== null) return;
      const session = selectedSession;
      const requestGeneration = generation;
      const epoch = requestEpoch;
      const abortController = newAbortController();
      const request = { abortController, epoch, generation: requestGeneration, session };
      previewRequest = request;
      try {
        const next = await fetchJson(
          `/api/v1/sessions/${session}/preview`,
          validatePreview,
          abortController.signal,
        );
        if (disposed || previewRequest !== request || epoch !== requestEpoch
          || requestGeneration !== generation || session !== selectedSession) return;
        const nextKey = JSON.stringify(next);
        const unchanged = snapshotKey !== null && snapshotKey === nextKey;
        snapshot = next;
        snapshotKey = nextKey;
        lastSuccessfulAt = monotonicNow();
        consecutiveFailures = 0;
        error = null;
        phase = unchanged ? "unchanged" : "fresh";
        emit();
      } catch (failure) {
        if (!disposed && previewRequest === request && epoch === requestEpoch
          && requestGeneration === generation && session === selectedSession) {
          applyFailure(failure);
        }
      } finally {
        if (previewRequest === request) previewRequest = null;
        schedulePoll(immediatePollPending ? 0 : POLL_INTERVAL_MS);
      }
    }

    async function fetchMetadata() {
      return auxiliary("/api/v1/meta", validateMetadata);
    }

    async function fetchRuntimeInfo() {
      return auxiliary("/api/v1/runtime/info", validateRuntimeInfo);
    }

    async function refreshSessions() {
      const result = await auxiliary("/api/v1/sessions", validateSessions);
      if (disposed) throw new StudioClientError("disposed");
      sessions = result;
      emit();
      return sessions;
    }

    function selectSession(session) {
      if (disposed) throw new StudioClientError("disposed");
      if (session !== null && (typeof session !== "string"
        || !SESSION_PATTERN.test(session))) {
        throw new StudioClientError("invalid_session");
      }
      generation += 1;
      requestEpoch += 1;
      clearScheduledPoll();
      immediatePollPending = false;
      abortPreview();
      selectedSession = session;
      snapshot = null;
      snapshotKey = null;
      lastSuccessfulAt = null;
      consecutiveFailures = 0;
      error = null;
      phase = session === null ? "idle" : (visible ? "connecting" : "paused");
      emit();
      schedulePoll(0);
    }

    function start() {
      if (disposed) throw new StudioClientError("disposed");
      observing = true;
      if (selectedSession !== null) {
        phase = visible
          ? (snapshot === null ? "connecting" : "stale")
          : "paused";
      }
      emit();
      schedulePoll(0);
    }

    function pause() {
      if (disposed) return;
      observing = false;
      requestEpoch += 1;
      clearScheduledPoll();
      immediatePollPending = false;
      abortPreview();
      if (selectedSession !== null) phase = "paused";
      emit();
    }

    function subscribe(listener) {
      if (disposed) throw new StudioClientError("disposed");
      if (typeof listener !== "function") {
        throw new StudioClientError("invalid_configuration");
      }
      listeners.add(listener);
      listener(state());
      return () => listeners.delete(listener);
    }

    function handleVisibility() {
      if (disposed) return;
      const next = visibility.isVisible();
      if (typeof next !== "boolean" || next === visible) return;
      visible = next;
      requestEpoch += 1;
      clearScheduledPoll();
      if (!visible) {
        immediatePollPending = false;
        abortPreview();
        if (selectedSession !== null) phase = "paused";
        emit();
        return;
      }
      if (selectedSession !== null) {
        phase = observing
          ? (snapshot === null ? "connecting" : "stale")
          : "paused";
      }
      emit();
      schedulePoll(0);
    }

    const unsubscribeVisibility = visibility.subscribe(handleVisibility);
    if (typeof unsubscribeVisibility !== "function") {
      throw new StudioClientError("invalid_configuration");
    }

    function dispose() {
      if (disposed) return;
      disposed = true;
      observing = false;
      requestEpoch += 1;
      clearScheduledPoll();
      immediatePollPending = false;
      abortPreview();
      auxiliaryRequests.forEach((controller) => controller.abort());
      unsubscribeVisibility();
      phase = "disposed";
      emit();
      listeners.clear();
    }

    if (typeof options.onState === "function") listeners.add(options.onState);
    const controller = {
      dispose,
      fetchMetadata,
      fetchRuntimeInfo,
      getState: state,
      pause,
      refreshSessions,
      selectSession,
      start,
      subscribe,
    };
    emit();
    return Object.freeze(controller);
  }

  root.HiyelxStudioHostClient = Object.freeze({ createController });
})(globalThis);
