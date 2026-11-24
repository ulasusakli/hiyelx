import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import {
  ProjectPathError,
  STARTER_TEMPLATES,
  UnsupportedProjectSchemaError,
  assertSafeRelativePath,
  createStarterProjectSnapshot,
  parseProjectManifestYaml,
  serializeProjectManifestYaml,
} from "@hiyelx/project-engine";
import {
  computeAutoLayout,
  parseRobotGraphYaml,
  projectDependsOn,
  validateDependencyDag,
} from "@hiyelx/graph-engine";
import {
  computeLineDiff,
  patchRobotConfigYamlRoundTrip,
  validateRobotConfigYaml,
} from "@hiyelx/config-engine";

describe("P4.2 shared engine packages", () => {
  it.each(STARTER_TEMPLATES)("creates valid project + RobotConfig v2 + graph for %s", (template) => {
    const bundle = createStarterProjectSnapshot(template, `id-${template}`, `Name ${template}`);
    const roundTripped = parseProjectManifestYaml(serializeProjectManifestYaml(bundle.manifest));
    expect(roundTripped).toEqual(bundle.manifest);

    const validatedConfig = validateRobotConfigYaml(bundle.robotYaml);
    expect(validatedConfig.ok).toBe(true);

    const graph = parseRobotGraphYaml(bundle.graphYaml);
    const dag = validateDependencyDag(graph);
    expect(dag.ok).toBe(true);
  });

  it("enforces workspace path confinement and fail-closed project schema checks", () => {
    expect(assertSafeRelativePath("robot/robot.yaml")).toBe("robot/robot.yaml");
    for (const bad of ["", "  ", "/etc/passwd", "../escape.yaml", "robot/../../x.yaml", "a\\b.yaml"]) {
      expect(() => assertSafeRelativePath(bad)).toThrow(ProjectPathError);
    }

    expect(() =>
      parseProjectManifestYaml('schema_version: "99"\nproject:\n  id: a\n  name: A\n'),
    ).toThrow(UnsupportedProjectSchemaError);
  });

  it("allows closed-loop feedback cycles while rejecting cyclic dependency edges", async () => {
    const bundle = createStarterProjectSnapshot("canonical-mock-rover", "rover-1", "Rover 1");
    const graph = parseRobotGraphYaml(bundle.graphYaml);
    const dag = validateDependencyDag(graph);
    expect(dag.ok).toBe(true);
    expect(projectDependsOn(graph)).toEqual({
      base_imu: ["drive_motor"],
      drive_motor: ["wheel_encoder"],
      front_camera: ["base_imu"],
      wheel_encoder: [],
    });

    const layout = await computeAutoLayout(graph);
    expect(Object.keys(layout).sort()).toEqual(graph.nodes.map((n) => n.id).sort());

    const cyclic = validateDependencyDag({
      schema_version: "1",
      nodes: [
        { id: "a", kind: "sensor", label: "A" },
        { id: "b", kind: "actuator", label: "B" },
      ],
      edges: [
        { id: "d1", source: "a", target: "b", kind: "dependency" },
        { id: "d2", source: "b", target: "a", kind: "dependency" },
      ],
    });
    expect(cyclic.ok).toBe(false);
    if (!cyclic.ok) {
      expect(cyclic.cycle).toEqual(["a", "b", "a"]);
    }
  });

  it("preserves YAML header comments on round-trip edits and computes clean line diffs", () => {
    const bundle = createStarterProjectSnapshot("canonical-mock-rover", "rover-1", "Rover 1");
    const parsed = validateRobotConfigYaml(bundle.robotYaml);
    expect(parsed.ok).toBe(true);
    if (!parsed.ok) return;

    const updatedYaml = patchRobotConfigYamlRoundTrip(bundle.robotYaml, {
      ...parsed.config,
      runtime: { ...parsed.config.runtime, tick_rate_hz: 100.0 },
    });
    expect(updatedYaml).toContain("# HIYELX Canonical Simulation Rover");
    const revalidated = validateRobotConfigYaml(updatedYaml);
    expect(revalidated.ok).toBe(true);
    if (revalidated.ok) {
      expect(revalidated.config.runtime.tick_rate_hz).toBe(100.0);
    }

    const diff = computeLineDiff(bundle.robotYaml, updatedYaml);
    expect(diff.some((line) => line.kind === "remove" && line.text.includes("50"))).toBe(true);
    expect(diff.some((line) => line.kind === "add" && line.text.includes("100"))).toBe(true);
  });

  it("fails closed on invalid YAML syntax, extra fields, or circular depends_on in robot.yaml", () => {
    const badSyntax = validateRobotConfigYaml("schema_version: [unterminated");
    expect(badSyntax.ok).toBe(false);

    const badVersion = validateRobotConfigYaml('schema_version: "1"\nrobot:\n  id: a\n  name: A\ncomponents: []\n');
    expect(badVersion.ok).toBe(false);

    const cyclicRobot = validateRobotConfigYaml([
      'schema_version: "2"',
      "robot:",
      '  id: "r1"',
      '  name: "R1"',
      "components:",
      '  - id: "m1"',
      '    category: "actuator"',
      '    model: "mock.motor"',
      '    depends_on: ["m2"]',
      '  - id: "m2"',
      '    category: "feedback"',
      '    model: "mock.encoder"',
      '    depends_on: ["m1"]',
    ].join("\n"));
    expect(cyclicRobot.ok).toBe(false);
    if (!cyclicRobot.ok) {
      expect(cyclicRobot.diagnostics.some((d) => d.message.includes("cycle"))).toBe(true);
    }
  });

  it("maintains strict contract parity with Python canonical examples/configs/mock-robot.yaml", () => {
    const testDir = path.dirname(fileURLToPath(import.meta.url));
    const canonicalPath = path.resolve(testDir, "../../../examples/configs/mock-robot.yaml");
    const yamlText = fs.readFileSync(canonicalPath, "utf8");
    const validated = validateRobotConfigYaml(yamlText);
    expect(validated.ok).toBe(true);
    if (validated.ok) {
      expect(validated.config.schema_version).toBe("2");
      expect(validated.config.robot.id).toBe("hiyelx-mock-rover-01");
      expect(validated.config.components.map((c) => c.id)).toEqual([
        "wheel_encoder",
        "drive_motor",
        "base_imu",
        "front_camera",
      ]);
    }
  });
});
