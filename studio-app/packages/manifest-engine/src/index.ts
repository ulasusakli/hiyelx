import { parse as parseYaml } from "yaml";
import { z } from "zod";
import {
  RUNTIME_COMPONENT_CATEGORIES,
  type RuntimeComponentCategory,
} from "@hiyelx/graph-engine";
import { assertSafeRelativePath } from "@hiyelx/project-engine";

export const SUPPORTED_MANIFEST_VERSION = "1.0" as const;

export const COMPONENT_CAPABILITIES = [
  "can_set_velocity",
  "can_set_position",
  "can_set_torque",
  "can_stream_frames",
  "has_rgb_frame",
  "has_depth_frame",
  "has_orientation_quaternion",
  "has_angular_velocity_3d",
  "has_linear_acceleration_3d",
  "has_encoder_ticks",
  "has_angular_position",
  "has_angular_velocity",
] as const;

export type ComponentCapability = (typeof COMPONENT_CAPABILITIES)[number];

export const MANIFEST_TYPES = ["driver", "component", "service"] as const;
export type ManifestType = (typeof MANIFEST_TYPES)[number];

const VERSION_PATTERN = /^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:(a|b|rc)(\d+))?$/;
const PRE_RANK: Record<string, number> = { a: 0, b: 1, rc: 2 };

export class UnsupportedManifestVersionError extends Error {
  readonly found: unknown;
  readonly expected: string;

  constructor(found: unknown, expected: string) {
    super(`Unsupported manifest_version "${String(found)}"; expected "${expected}"`);
    this.name = "UnsupportedManifestVersionError";
    this.found = found;
    this.expected = expected;
  }
}

const versionStringSchema = z
  .string()
  .refine((value) => VERSION_PATTERN.test(value), "Expected MAJOR.MINOR.PATCH[a|b|rcN]");

const nonBlankStringSchema = z
  .string()
  .refine((value) => value.trim().length > 0, "Field must not be blank");

const safeSchemaPath = z.string().superRefine((val, ctx) => {
  try {
    assertSafeRelativePath(val);
  } catch (error) {
    ctx.addIssue({
      code: z.ZodIssueCode.custom,
      message: error instanceof Error ? error.message : "Invalid relative schema path",
    });
  }
});

export const manifestInterfaceSchema = z
  .object({
    name: nonBlankStringSchema,
    type: nonBlankStringSchema,
    direction: z.enum(["input", "output", "bidirectional"]).default("bidirectional"),
  })
  .strict();

export const manifestDependencySchema = z
  .object({
    id: nonBlankStringSchema,
    min_version: versionStringSchema.nullable().optional(),
  })
  .strict();

export const componentManifestSchema = z
  .object({
    manifest_version: z.literal(SUPPORTED_MANIFEST_VERSION),
    id: nonBlankStringSchema,
    model: nonBlankStringSchema,
    name: nonBlankStringSchema,
    version: versionStringSchema,
    type: z.enum(MANIFEST_TYPES),
    category: z.enum(RUNTIME_COMPONENT_CATEGORIES),
    description: z.string().nullable().optional(),
    runtime: z
      .object({
        min_version: versionStringSchema,
        max_version: versionStringSchema.nullable().optional(),
      })
      .strict(),
    capabilities: z.array(z.enum(COMPONENT_CAPABILITIES)).default([]),
    interfaces: z.array(manifestInterfaceSchema).default([]),
    dependencies: z.array(manifestDependencySchema).default([]),
    configuration: z
      .object({
        schema: safeSchemaPath,
        defaults: z.record(z.string(), z.unknown()).default({}),
      })
      .strict(),
    scaffold_command: z.string().nullable().optional(),
  })
  .strict()
  .superRefine((manifest, ctx) => {
    if (new Set(manifest.capabilities).size !== manifest.capabilities.length) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        path: ["capabilities"],
        message: `Manifest "${manifest.id}" contains duplicate capabilities`,
      });
    }
    const depIds = manifest.dependencies.map((d) => d.id);
    if (depIds.includes(manifest.id)) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        path: ["dependencies"],
        message: `Manifest "${manifest.id}" cannot depend on itself`,
      });
    }
  });

export type ComponentManifest = z.infer<typeof componentManifestSchema>;

export function parseManifestYaml(source: string): ComponentManifest {
  const raw: unknown = parseYaml(source);
  if (raw === null || typeof raw !== "object" || Array.isArray(raw)) {
    throw new Error("Manifest root must be a YAML mapping");
  }
  const version = (raw as Record<string, unknown>)["manifest_version"];
  if (version !== SUPPORTED_MANIFEST_VERSION) {
    throw new UnsupportedManifestVersionError(version ?? "missing", SUPPORTED_MANIFEST_VERSION);
  }
  return componentManifestSchema.parse(raw);
}

export function compareVersions(a: string, b: string): number {
  const ka = parseVersionTuple(a);
  const kb = parseVersionTuple(b);
  for (let i = 0; i < 5; i += 1) {
    const diff = (ka[i] ?? 0) - (kb[i] ?? 0);
    if (diff !== 0) return diff;
  }
  return 0;
}

function parseVersionTuple(version: string): readonly [number, number, number, number, number] {
  const match = VERSION_PATTERN.exec(version);
  if (match === null) {
    throw new Error(`Invalid version "${version}"`);
  }
  const major = Number(match[1]);
  const minor = Number(match[2]);
  const patch = Number(match[3]);
  const preTag = match[4];
  if (preTag === undefined) return [major, minor, patch, 3, 0];
  return [major, minor, patch, PRE_RANK[preTag] ?? 0, Number(match[5])];
}

export type CompatibilityStatus =
  | "compatible"
  | "incompatible_runtime"
  | "missing_dependency"
  | "incompatible_dependency"
  | "dependency_cycle";

export interface CompatibilityIssue {
  readonly code: CompatibilityStatus;
  readonly message: string;
  readonly targetId: string | null;
}

export interface CompatibilityReport {
  readonly manifestId: string;
  readonly runtimeVersion: string;
  readonly compatible: boolean;
  readonly status: CompatibilityStatus;
  readonly issues: readonly CompatibilityIssue[];
  readonly resolvedOrder: readonly string[];
}

export function evaluateManifestCompatibility(
  manifest: ComponentManifest,
  runtimeVersion: string,
  catalog: readonly ComponentManifest[] = [],
): CompatibilityReport {
  const byId = new Map<string, ComponentManifest>();
  for (const item of catalog) byId.set(item.id, item);
  byId.set(manifest.id, manifest);

  const issues: CompatibilityIssue[] = [];

  if (compareVersions(runtimeVersion, manifest.runtime.min_version) < 0) {
    issues.push({
      code: "incompatible_runtime",
      targetId: manifest.id,
      message: `${manifest.id} requires runtime >= ${manifest.runtime.min_version} (current: ${runtimeVersion})`,
    });
  }
  if (
    manifest.runtime.max_version !== undefined &&
    manifest.runtime.max_version !== null &&
    compareVersions(runtimeVersion, manifest.runtime.max_version) > 0
  ) {
    issues.push({
      code: "incompatible_runtime",
      targetId: manifest.id,
      message: `${manifest.id} requires runtime <= ${manifest.runtime.max_version} (current: ${runtimeVersion})`,
    });
  }

  const resolvedOrder: string[] = [];
  const visiting: string[] = [];
  const visited = new Set<string>();

  function resolve(current: ComponentManifest): void {
    if (visited.has(current.id)) return;
    const cycleStart = visiting.indexOf(current.id);
    if (cycleStart !== -1) {
      const chain = [...visiting.slice(cycleStart), current.id].join(" -> ");
      issues.push({
        code: "dependency_cycle",
        targetId: current.id,
        message: `Manifest dependency cycle detected: ${chain}`,
      });
      return;
    }

    visiting.push(current.id);
    for (const dep of current.dependencies) {
      const depManifest = byId.get(dep.id);
      if (depManifest === undefined) {
        issues.push({
          code: "missing_dependency",
          targetId: dep.id,
          message: `${current.id} requires missing dependency "${dep.id}"`,
        });
        continue;
      }
      if (
        dep.min_version !== undefined &&
        dep.min_version !== null &&
        compareVersions(depManifest.version, dep.min_version) < 0
      ) {
        issues.push({
          code: "incompatible_dependency",
          targetId: dep.id,
          message: `${current.id} requires ${dep.id} >= ${dep.min_version} (found ${depManifest.version})`,
        });
      }
      resolve(depManifest);
    }
    visiting.pop();
    visited.add(current.id);
    resolvedOrder.push(current.id);
  }

  resolve(manifest);

  const firstIssue = issues[0];
  if (firstIssue === undefined) {
    return {
      manifestId: manifest.id,
      runtimeVersion,
      compatible: true,
      status: "compatible",
      issues: [],
      resolvedOrder,
    };
  }
  return {
    manifestId: manifest.id,
    runtimeVersion,
    compatible: false,
    status: firstIssue.code,
    issues,
    resolvedOrder,
  };
}

export interface ManifestFilterOptions {
  readonly query?: string;
  readonly category?: RuntimeComponentCategory | "all";
  readonly capability?: ComponentCapability | "all";
  readonly compatibleOnly?: boolean;
  readonly runtimeVersion?: string;
}

export function filterManifests(
  catalog: readonly ComponentManifest[],
  options: ManifestFilterOptions,
): readonly ComponentManifest[] {
  const q = (options.query ?? "").trim().toLowerCase();
  const runtimeVersion = options.runtimeVersion ?? "0.2.0a1";

  return catalog.filter((item) => {
    if (options.category && options.category !== "all" && item.category !== options.category) {
      return false;
    }
    if (
      options.capability &&
      options.capability !== "all" &&
      !item.capabilities.includes(options.capability)
    ) {
      return false;
    }
    if (options.compatibleOnly) {
      const report = evaluateManifestCompatibility(item, runtimeVersion, catalog);
      if (!report.compatible) return false;
    }
    if (q.length > 0) {
      const haystack = `${item.id} ${item.name} ${item.model} ${item.description ?? ""}`.toLowerCase();
      if (!haystack.includes(q)) return false;
    }
    return true;
  });
}

export const BUILTIN_MANIFEST_CATALOG: readonly ComponentManifest[] = [
  componentManifestSchema.parse({
    manifest_version: "1.0",
    id: "hiyelx.camera.mock",
    model: "mock.camera",
    name: "Mock RGB Camera",
    version: "0.2.0a1",
    type: "component",
    category: "vision",
    description: "Hardware-free deterministic mock RGB camera component.",
    runtime: { min_version: "0.2.0a1" },
    capabilities: ["can_stream_frames", "has_rgb_frame"],
    interfaces: [{ name: "frame", type: "camera.frame", direction: "output" }],
    dependencies: [],
    configuration: {
      schema: "settings.schema.json",
      defaults: { width: 640, height: 480, fps: 30 },
    },
  }),
  componentManifestSchema.parse({
    manifest_version: "1.0",
    id: "hiyelx.encoder.mock",
    model: "mock.encoder",
    name: "Mock Wheel Encoder",
    version: "0.2.0a1",
    type: "component",
    category: "feedback",
    description: "Hardware-free deterministic quadrature encoder feedback component.",
    runtime: { min_version: "0.2.0a1" },
    capabilities: ["has_encoder_ticks", "has_angular_position", "has_angular_velocity"],
    interfaces: [{ name: "state", type: "encoder.state", direction: "output" }],
    dependencies: [],
    configuration: {
      schema: "settings.schema.json",
      defaults: { resolution: 4096 },
    },
  }),
  componentManifestSchema.parse({
    manifest_version: "1.0",
    id: "hiyelx.imu.mock",
    model: "mock.imu",
    name: "Mock 9-DOF IMU",
    version: "0.2.0a1",
    type: "component",
    category: "spatial",
    description: "Hardware-free deterministic inertial measurement component.",
    runtime: { min_version: "0.2.0a1" },
    capabilities: [
      "has_orientation_quaternion",
      "has_angular_velocity_3d",
      "has_linear_acceleration_3d",
    ],
    interfaces: [{ name: "imu", type: "imu.measurement", direction: "output" }],
    dependencies: [],
    configuration: {
      schema: "settings.schema.json",
      defaults: { sample_rate_hz: 100.0 },
    },
  }),
  componentManifestSchema.parse({
    manifest_version: "1.0",
    id: "hiyelx.motor.dynamixel.xl430",
    model: "motor.dynamixel.xl430",
    name: "DYNAMIXEL XL430-W250-T Motor Driver",
    version: "0.2.0a1",
    type: "driver",
    category: "actuator",
    description:
      "Reference Protocol 2.0 serial motor driver (opt-in bench track; software readiness only).",
    runtime: { min_version: "0.1.0" },
    capabilities: ["can_set_velocity", "has_angular_position", "has_angular_velocity"],
    interfaces: [
      { name: "command", type: "motor.command", direction: "input" },
      { name: "state", type: "motor.state", direction: "output" },
    ],
    dependencies: [],
    configuration: {
      schema: "settings.schema.json",
      defaults: { port: "/dev/ttyUSB0", baudrate: 57600, motor_id: 1 },
    },
    scaffold_command:
      "hiyelx scaffold motor-driver ./acme-driver --package-name acme_motor_driver --model-name motor.acme.reference",
  }),
  componentManifestSchema.parse({
    manifest_version: "1.0",
    id: "hiyelx.motor.mock",
    model: "mock.motor",
    name: "Mock Drive Motor",
    version: "0.2.0a1",
    type: "component",
    category: "actuator",
    description: "Hardware-free canonical mock actuator component for RobotConfig v2.",
    runtime: { min_version: "0.2.0a1" },
    capabilities: ["can_set_velocity", "has_angular_position", "has_angular_velocity"],
    interfaces: [
      { name: "command", type: "motor.command", direction: "input" },
      { name: "state", type: "motor.state", direction: "output" },
    ],
    dependencies: [],
    configuration: {
      schema: "settings.schema.json",
      defaults: { max_rpm: 300.0 },
    },
  }),
  componentManifestSchema.parse({
    manifest_version: "1.0",
    id: "hiyelx.motor.simulated",
    model: "motor.simulated",
    name: "Deterministic Simulated Motor",
    version: "0.2.0a1",
    type: "driver",
    category: "actuator",
    description: "Explicit-time deterministic simulated motor driver.",
    runtime: { min_version: "0.1.0" },
    capabilities: ["can_set_velocity", "has_angular_position", "has_angular_velocity"],
    interfaces: [
      { name: "command", type: "motor.command", direction: "input" },
      { name: "state", type: "motor.state", direction: "output" },
    ],
    dependencies: [],
    configuration: {
      schema: "settings.schema.json",
      defaults: {},
    },
    scaffold_command:
      "hiyelx scaffold motor-driver ./acme-driver --package-name acme_motor_driver --model-name motor.acme.reference",
  }),
];
