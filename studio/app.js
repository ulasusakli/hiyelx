(function () {
  "use strict";

  const fixtures = window.HiyelxStudioFixtures;
  const fixtureSelect = document.getElementById("fixture-select");
  const resourceGrid = document.getElementById("resource-grid");
  const emptyState = document.getElementById("empty-state");

  function textNode(tag, className, text) {
    const element = document.createElement(tag);
    if (className) element.className = className;
    element.textContent = text;
    return element;
  }

  function makeValue(label, value, unit, description) {
    const wrapper = document.createElement("div");
    wrapper.className = "metric";
    const labelId = `metric-${label.toLowerCase().replaceAll(" ", "-")}`;
    wrapper.append(textNode("span", "metric-label", label));
    const output = textNode("span", "metric-value", value);
    output.setAttribute("aria-label", `${label}: ${value} ${unit}`);
    wrapper.append(output, textNode("span", "metric-unit", unit));
    if (description) {
      const help = textNode("span", "sr-only", description);
      help.id = labelId;
      output.setAttribute("aria-describedby", labelId);
      wrapper.append(help);
    }
    return wrapper;
  }

  function renderResources(snapshot) {
    resourceGrid.replaceChildren();
    if (!snapshot || snapshot.resources.length === 0) {
      resourceGrid.hidden = true;
      emptyState.hidden = false;
      return;
    }

    resourceGrid.hidden = false;
    emptyState.hidden = true;
    snapshot.resources.forEach((resource, index) => {
      const card = document.createElement("article");
      card.className = "resource-card panel";
      card.setAttribute("aria-labelledby", `resource-title-${index}`);

      const cardHeader = document.createElement("div");
      cardHeader.className = "resource-card-header";
      const identityBlock = document.createElement("div");
      identityBlock.append(
        textNode("span", "field-label", "Resource identity"),
        textNode("h3", "resource-identity", resource.identity),
      );
      const kind = document.createElement("span");
      kind.className = "kind-pill";
      kind.textContent = resource.kind;
      cardHeader.append(identityBlock, kind);
      card.append(cardHeader);
      card.querySelector("h3").id = `resource-title-${index}`;

      const lifecycle = document.createElement("div");
      lifecycle.className = "resource-status-row";
      lifecycle.append(
        textNode("span", "field-label", "Lifecycle"),
        textNode("span", "status-pill", resource.lifecycle_state),
        textNode("span", "field-label", "Health"),
        textNode("span", "status-pill health-pill", resource.health_status),
      );
      card.append(lifecycle);
      card.append(textNode("p", "health-summary", resource.health_summary || "No health summary reported."));

      const metrics = document.createElement("div");
      metrics.className = "metrics-grid";
      metrics.append(
        makeValue("Position", fixtures.formatNumber(resource.state.angular_position_radians, 3), "rad"),
        makeValue("Velocity", fixtures.formatNumber(resource.state.angular_velocity_radians_per_second, 3), "rad/s"),
        makeValue("Simulation time", fixtures.formatNumber(resource.state.simulation_time_seconds, 1), "simulated s"),
        makeValue(
          "Revision",
          String(resource.state.revision),
          "state mutations",
          "Revision counts successful resource-state mutations. Preview reads do not increment it. Equal revisions do not prove the whole runtime snapshot is unchanged; revision is not physical movement or hardware evidence.",
        ),
      );
      card.append(metrics);
      resourceGrid.append(card);
    });
  }

  function renderScenario(scenario) {
    const badge = document.getElementById("connection-badge");
    badge.dataset.severity = scenario.severity;
    document.getElementById("connection-label").textContent = scenario.badge;
    const statePill = document.getElementById("state-pill");
    statePill.dataset.severity = scenario.severity;
    statePill.textContent = scenario.badge;
    document.getElementById("state-message").dataset.severity = scenario.severity;
    document.getElementById("state-message-text").textContent = scenario.message;
    document.getElementById("freshness").textContent = scenario.freshness;
    document.getElementById("snapshot-state").textContent = scenario.snapshot ? "Fixture data" : "No snapshot";
    document.getElementById("runtime-state").textContent = scenario.snapshot
      ? scenario.snapshot.runtime_state
      : "—";
    document.getElementById("resource-count").textContent = scenario.snapshot
      ? String(scenario.snapshot.resources.length)
      : "0";
    renderResources(scenario.snapshot);
  }

  fixtures.scenarios.forEach((scenario) => {
    const option = document.createElement("option");
    option.value = scenario.id;
    option.textContent = scenario.label;
    option.selected = scenario.id === "fresh";
    fixtureSelect.append(option);
  });
  fixtureSelect.addEventListener("change", () => {
    renderScenario(fixtures.getScenario(fixtureSelect.value));
  });
  renderScenario(fixtures.getScenario(fixtureSelect.value));
})();
