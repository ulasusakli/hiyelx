import { parse as parseYaml, stringify as stringifyYaml } from "yaml";
import { z } from "zod";

export const SUPPORTED_PROJECT_SCHEMA_VERSION = "1" as const;
export const SUPPORTED_LAYOUT_SCHEMA_VERSION = "1" as const;

export const STARTER_TEMPLATES = [
  "canonical-mock-rover",
  "single-sim-motor",
  "blank-robot",
] as const;

export type StarterTemplate = (typeof STARTER_TEMPLATES)[number];

export class ProjectPathError extends Error {
  readonly path: string;

  constructor(path: string, reason: string) {
    super(`Unsafe workspace path "${path}": ${reason}`);
    this.name = "ProjectPathError";
    this.path = path;
  }
}

export class UnsupportedProjectSchemaError extends Error {
  readonly found: unknown;
  readonly expected: string;

  constructor(found: unknown, expected: string) {
    super(`Unsupported schema_version "${String(found)}"; expected "${expected}"`);
    this.name = "UnsupportedProjectSchemaError";
    this.found = found;
    this.expected = expected;
  }
}

export function assertSafeRelativePath(value: string): string {
  if (value.trim().length === 0) {
    throw new ProjectPathError(value, "path must not be blank");
  }
  if (value.includes("\\") || value.startsWith("/")) {
    throw new ProjectPathError(value, "path must be relative POSIX");
  }
  const parts = value.split("/");
  if (parts.some((part) => part === "" || part === "." || part === "..")) {
    throw new ProjectPathError(value, "path must not contain traversal segments");
  }
  return value;
}

const safeRelativePathSchema = z.string().superRefine((val, ctx) => {
  try {
    assertSafeRelativePath(val);
  } catch (error) {
    ctx.addIssue({
      code: z.ZodIssueCode.custom,
      message: error instanceof Error ? error.message : "Invalid relative workspace path",
    });
  }
});

const nonBlankStringSchema = z
  .string()
  .refine((value) => value.trim().length > 0, "Field must not be blank");

export const projectMetadataSchema = z
  .object({
    id: nonBlankStringSchema,
    name: nonBlankStringSchema,
    version: nonBlankStringSchema.default("0.1.0"),
    description: z.string().nullable().optional(),
    template: z.string().nullable().optional(),
  })
  .strict();

export const workspacePathsSchema = z
  .object({
    robot_config: safeRelativePathSchema.default("robot/robot.yaml"),
    graph_file: safeRelativePathSchema.default("robot/connections/graph.yaml"),
    layout_file: safeRelativePathSchema.default("robot/connections/layout.yaml"),
    default_profile: nonBlankStringSchema.default("sim"),
  })
  .strict();

export const profileDefinitionSchema = z
  .object({
    description: nonBlankStringSchema,
    overrides: safeRelativePathSchema,
  })
  .strict();

export const projectRuntimeContractSchema = z
  .object({
    min_version: nonBlankStringSchema.default("0.2.0a1"),
    robot_schema_version: z.literal("2").default("2"),
  })
  .strict();

export const projectManifestSchema = z
  .object({
    schema_version: z.literal(SUPPORTED_PROJECT_SCHEMA_VERSION),
    project: projectMetadataSchema,
    workspace: workspacePathsSchema.default({
      robot_config: "robot/robot.yaml",
      graph_file: "robot/connections/graph.yaml",
      layout_file: "robot/connections/layout.yaml",
      default_profile: "sim",
    }),
    profiles: z.record(z.string(), profileDefinitionSchema).default({}),
    runtime: projectRuntimeContractSchema.default({
      min_version: "0.2.0a1",
      robot_schema_version: "2",
    }),
  })
  .strict()
  .superRefine((manifest, ctx) => {
    const profileNames = Object.keys(manifest.profiles);
    if (profileNames.length > 0 && !Object.hasOwn(manifest.profiles, manifest.workspace.default_profile)) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        path: ["workspace", "default_profile"],
        message: `default_profile "${manifest.workspace.default_profile}" is not defined in profiles`,
      });
    }
  });

export type ProjectManifest = z.infer<typeof projectManifestSchema>;

export const nodePositionSchema = z
  .object({
    x: z.number().finite(),
    y: z.number().finite(),
  })
  .strict();

export const canvasLayoutDocumentSchema = z
  .object({
    schema_version: z.literal(SUPPORTED_LAYOUT_SCHEMA_VERSION),
    positions: z.record(z.string(), nodePositionSchema).default({}),
  })
  .strict();

export type NodePosition = z.infer<typeof nodePositionSchema>;
export type CanvasLayoutDocument = z.infer<typeof canvasLayoutDocumentSchema>;

export function parseProjectManifestYaml(source: string): ProjectManifest {
  const raw: unknown = parseYaml(source);
  if (raw === null || typeof raw !== "object" || Array.isArray(raw)) {
    throw new Error("Project manifest root must be a YAML mapping");
  }
  const version = (raw as Record<string, unknown>)["schema_version"];
  if (version !== SUPPORTED_PROJECT_SCHEMA_VERSION) {
    throw new UnsupportedProjectSchemaError(version ?? "missing", SUPPORTED_PROJECT_SCHEMA_VERSION);
  }
  return projectManifestSchema.parse(raw);
}

export function serializeProjectManifestYaml(manifest: ProjectManifest): string {
  const validated = projectManifestSchema.parse(manifest);
  return stringifyYaml(validated);
}

export interface ProjectWorkspaceSnapshot {
  readonly manifest: ProjectManifest;
  readonly robotYaml: string;
  readonly graphYaml: string;
  readonly layout: CanvasLayoutDocument;
}

export function createStarterProjectSnapshot(
  template: StarterTemplate,
  projectId: string,
  projectName: string,
): ProjectWorkspaceSnapshot {
  const manifest = projectManifestSchema.parse({
    schema_version: "1",
    project: {
      id: projectId,
      name: projectName,
      version: "0.1.0",
      description: `HIYELX Studio project (${template})`,
      template,
    },
    workspace: {
      robot_config: "robot/robot.yaml",
      graph_file: "robot/connections/graph.yaml",
      layout_file: "robot/connections/layout.yaml",
      default_profile: "sim",
    },
    profiles: {
      sim: {
        description: "Deterministic local simulation profile",
        overrides: "configs/sim.yaml",
      },
      dev: {
        description: "Local developer profile",
        overrides: "configs/dev.yaml",
      },
    },
    runtime: {
      min_version: "0.2.0a1",
      robot_schema_version: "2",
    },
  });

  if (template === "canonical-mock-rover") {
    return {
      manifest,
      robotYaml: [
        "# HIYELX Canonical Simulation Rover",
        'schema_version: "2"',
        "robot:",
        `  id: "${projectId}"`,
        `  name: "${projectName}"`,
        '  version: "0.1.0"',
        "runtime:",
        "  tick_rate_hz: 50.0",
        '  log_level: "INFO"',
        "  history_retention_days: 7",
        "components:",
        '  - id: "wheel_encoder"',
        '    category: "feedback"',
        '    model: "mock.encoder"',
        "    settings:",
        "      resolution: 4096",
        '  - id: "drive_motor"',
        '    category: "actuator"',
        '    model: "mock.motor"',
        "    depends_on:",
        '      - "wheel_encoder"',
        "    settings:",
        "      max_rpm: 300.0",
        '  - id: "base_imu"',
        '    category: "spatial"',
        '    model: "mock.imu"',
        "    depends_on:",
        '      - "drive_motor"',
        "    settings:",
        "      sample_rate_hz: 100.0",
        '  - id: "front_camera"',
        '    category: "vision"',
        '    model: "mock.camera"',
        "    depends_on:",
        '      - "base_imu"',
        "    settings:",
        "      width: 640",
        "      height: 480",
        "      fps: 30",
        "",
      ].join("\n"),
      graphYaml: stringifyYaml({
        schema_version: "1",
        nodes: [
          {
            id: "wheel_encoder",
            kind: "sensor",
            label: "Wheel Encoder",
            component_id: "wheel_encoder",
            category: "feedback",
            model: "mock.encoder",
          },
          {
            id: "motion_controller",
            kind: "controller",
            label: "Motion Controller",
          },
          {
            id: "drive_motor",
            kind: "actuator",
            label: "Drive Motor",
            component_id: "drive_motor",
            category: "actuator",
            model: "mock.motor",
          },
          {
            id: "base_imu",
            kind: "sensor",
            label: "Base IMU",
            component_id: "base_imu",
            category: "spatial",
            model: "mock.imu",
          },
          {
            id: "front_camera",
            kind: "sensor",
            label: "Front Camera",
            component_id: "front_camera",
            category: "vision",
            model: "mock.camera",
          },
        ],
        edges: [
          { id: "dep-enc-motor", source: "wheel_encoder", target: "drive_motor", kind: "dependency" },
          { id: "dep-motor-imu", source: "drive_motor", target: "base_imu", kind: "dependency" },
          { id: "dep-imu-cam", source: "base_imu", target: "front_camera", kind: "dependency" },
          { id: "data-enc-ctrl", source: "wheel_encoder", target: "motion_controller", kind: "data", topic: "encoder/ticks" },
          { id: "cmd-ctrl-motor", source: "motion_controller", target: "drive_motor", kind: "command", topic: "motor/velocity_cmd" },
          { id: "fb-motor-ctrl", source: "drive_motor", target: "motion_controller", kind: "feedback", topic: "motor/state" },
        ],
      }),
      layout: {
        schema_version: "1",
        positions: {
          wheel_encoder: { x: 80, y: 120 },
          motion_controller: { x: 340, y: 120 },
          drive_motor: { x: 600, y: 120 },
          base_imu: { x: 340, y: 300 },
          front_camera: { x: 600, y: 300 },
        },
      },
    };
  }

  if (template === "single-sim-motor") {
    return {
      manifest,
      robotYaml: [
        'schema_version: "2"',
        "robot:",
        `  id: "${projectId}"`,
        `  name: "${projectName}"`,
        '  version: "0.1.0"',
        "runtime:",
        "  tick_rate_hz: 50.0",
        '  log_level: "INFO"',
        "  history_retention_days: 7",
        "components:",
        '  - id: "sim_motor"',
        '    category: "actuator"',
        '    model: "mock.motor"',
        "    settings:",
        "      max_rpm: 300.0",
        "",
      ].join("\n"),
      graphYaml: stringifyYaml({
        schema_version: "1",
        nodes: [
          {
            id: "sim_motor",
            kind: "actuator",
            label: "Simulated Motor",
            component_id: "sim_motor",
            category: "actuator",
            model: "mock.motor",
          },
        ],
        edges: [],
      }),
      layout: {
        schema_version: "1",
        positions: { sim_motor: { x: 240, y: 160 } },
      },
    };
  }

  return {
    manifest,
    robotYaml: [
      'schema_version: "2"',
      "robot:",
      `  id: "${projectId}"`,
      `  name: "${projectName}"`,
      '  version: "0.1.0"',
      "runtime:",
      "  tick_rate_hz: 100.0",
      '  log_level: "INFO"',
      "  history_retention_days: 7",
      "components: []",
      "",
    ].join("\n"),
    graphYaml: stringifyYaml({ schema_version: "1", nodes: [], edges: [] }),
    layout: { schema_version: "1", positions: {} },
  };
}
