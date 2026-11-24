import { describe, expect, it } from "vitest";
import { validateRobotConfigYaml } from "@hiyelx/config-engine";
import { createStarterProjectSnapshot } from "@hiyelx/project-engine";
import {
  createStarterWorkflow,
  parseApplicationWorkflowYaml,
  serializeApplicationWorkflowYaml,
  validateWorkflowAgainstRobot,
} from "@hiyelx/workflow-engine";

describe("P6.1 @hiyelx/workflow-engine", () => {
  it("round-trips applications/main.yaml and cross-validates against RobotConfig v2", () => {
    const project = createStarterProjectSnapshot("canonical-mock-rover", "rover-1", "Rover 1");
    const validatedRobot = validateRobotConfigYaml(project.robotYaml);
    expect(validatedRobot.ok).toBe(true);
    if (!validatedRobot.ok) return;

    const workflow = createStarterWorkflow(validatedRobot.config);
    const yaml = serializeApplicationWorkflowYaml(workflow);
    const reloaded = parseApplicationWorkflowYaml(yaml);
    expect(reloaded).toEqual(workflow);
    expect(validateWorkflowAgainstRobot(reloaded, validatedRobot.config)).toEqual([]);
  });

  it("detects dangling component targets and rejects unsupported schema versions", () => {
    const project = createStarterProjectSnapshot("single-sim-motor", "m1", "Motor 1");
    const validatedRobot = validateRobotConfigYaml(project.robotYaml);
    expect(validatedRobot.ok).toBe(true);
    if (!validatedRobot.ok) return;

    const brokenWorkflow = parseApplicationWorkflowYaml(`
schema_version: "1"
application:
  id: bad-target
  name: Bad Target
tasks:
  - id: step1
    name: Move Arm
    target_component: nonexistent_arm
    action: set_velocity
    timeout_ms: 1500
    on_fault: safe_stop
`);
    const issues = validateWorkflowAgainstRobot(brokenWorkflow, validatedRobot.config);
    expect(issues).toHaveLength(1);
    expect(issues[0]?.message).toContain("nonexistent_arm");

    expect(() =>
      parseApplicationWorkflowYaml('schema_version: "99"\napplication:\n  id: x\n  name: X\n'),
    ).toThrow(/Unsupported workflow schema_version/);
  });
});
