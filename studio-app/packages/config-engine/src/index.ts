import {
  YAMLParseError,
  parseDocument,
  stringify as stringifyYaml,
} from "yaml";
import { z } from "zod";
import {
  RUNTIME_COMPONENT_CATEGORIES,
  type RuntimeComponentCategory,
} from "@hiyelx/graph-engine";

export const SUPPORTED_ROBOT_SCHEMA_VERSION = "2" as const;

const nonBlank = z.string().refine((value) => value.trim().length > 0, "Must not be blank");

export const robotMetadataSchema = z
  .object({
    id: nonBlank,
    name: nonBlank,
    version: nonBlank.default("0.1.0"),
    description: z.string().nullable().optional(),
  })
  .strict();

export const runtimeSettingsSchema = z
  .object({
    tick_rate_hz: z.number().finite().positive().default(100.0),
    log_level: nonBlank.default("INFO"),
    history_retention_days: z.number().int().nonnegative().default(7),
  })
  .strict();

export const componentDefinitionSchema = z
  .object({
    id: nonBlank,
    category: z.enum(RUNTIME_COMPONENT_CATEGORIES),
    model: nonBlank,
    driver: nonBlank.nullable().optional(),
    settings: z.record(z.string(), z.unknown()).default({}),
    depends_on: z.array(nonBlank).default([]),
  })
  .strict();

export const robotConfigSchema = z
  .object({
    schema_version: z.literal(SUPPORTED_ROBOT_SCHEMA_VERSION),
    robot: robotMetadataSchema,
    runtime: runtimeSettingsSchema.default({
      tick_rate_hz: 100.0,
      log_level: "INFO",
      history_retention_days: 7,
    }),
    components: z.array(componentDefinitionSchema),
  })
  .strict()
  .superRefine((config, ctx) => {
    const ids = new Set<string>();
    for (const [index, comp] of config.components.entries()) {
      if (ids.has(comp.id)) {
        ctx.addIssue({
          code: z.ZodIssueCode.custom,
          path: ["components", index, "id"],
          message: `Duplicate component identity "${comp.id}"`,
        });
      }
      ids.add(comp.id);
    }

    for (const [index, comp] of config.components.entries()) {
      const seenDeps = new Set<string>();
      for (const dep of comp.depends_on) {
        if (dep === comp.id) {
          ctx.addIssue({
            code: z.ZodIssueCode.custom,
            path: ["components", index, "depends_on"],
            message: `Component "${comp.id}" cannot depend on itself`,
          });
        } else if (!ids.has(dep)) {
          ctx.addIssue({
            code: z.ZodIssueCode.custom,
            path: ["components", index, "depends_on"],
            message: `Component "${comp.id}" depends on unknown component "${dep}"`,
          });
        } else if (seenDeps.has(dep)) {
          ctx.addIssue({
            code: z.ZodIssueCode.custom,
            path: ["components", index, "depends_on"],
            message: `Component "${comp.id}" lists duplicate dependency "${dep}"`,
          });
        }
        seenDeps.add(dep);
      }
    }

    const cycle = detectComponentDependencyCycle(config.components);
    if (cycle !== null) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        path: ["components"],
        message: `Lifecycle dependency cycle detected: ${cycle.join(" -> ")}`,
      });
    }
  });

export type ComponentDefinition = z.infer<typeof componentDefinitionSchema>;
export type RobotConfig = z.infer<typeof robotConfigSchema>;

function detectComponentDependencyCycle(
  components: readonly ComponentDefinition[],
): string[] | null {
  const depsById = new Map<string, readonly string[]>();
  for (const comp of components) {
    depsById.set(comp.id, comp.depends_on);
  }
  const visited = new Set<string>();
  const active = new Map<string, number>();
  const stack: string[] = [];

  function dfs(id: string): string[] | null {
    const existing = active.get(id);
    if (existing !== undefined) return [...stack.slice(existing), id];
    if (visited.has(id)) return null;
    active.set(id, stack.length);
    stack.push(id);
    for (const dep of [...(depsById.get(id) ?? [])].sort()) {
      if (!depsById.has(dep)) continue;
      const found = dfs(dep);
      if (found !== null) return found;
    }
    stack.pop();
    active.delete(id);
    visited.add(id);
    return null;
  }

  for (const id of [...depsById.keys()].sort()) {
    const found = dfs(id);
    if (found !== null) return found;
  }
  return null;
}

export interface ConfigValidationDiagnostic {
  readonly path: string;
  readonly message: string;
  readonly line: number | null;
  readonly column: number | null;
}

export type RobotConfigValidationResult =
  | { readonly ok: true; readonly config: RobotConfig; readonly diagnostics: readonly [] }
  | { readonly ok: false; readonly config: null; readonly diagnostics: readonly ConfigValidationDiagnostic[] };

/**
 * Fail-closed RobotConfig v2 parser & validator with line/column diagnostics.
 */
export function validateRobotConfigYaml(source: string): RobotConfigValidationResult {
  const doc = parseDocument(source, { prettyErrors: true });
  if (doc.errors.length > 0) {
    return {
      ok: false,
      config: null,
      diagnostics: doc.errors.map((err) => {
        const pos = err instanceof YAMLParseError ? err.linePos?.[0] : undefined;
        return {
          path: "<yaml>",
          message: err.message,
          line: pos?.line ?? null,
          column: pos?.col ?? null,
        };
      }),
    };
  }

  const raw: unknown = doc.toJS();
  if (raw === null || typeof raw !== "object" || Array.isArray(raw)) {
    return {
      ok: false,
      config: null,
      diagnostics: [
        {
          path: "<root>",
          message: "Document root must be a YAML mapping",
          line: 1,
          column: 1,
        },
      ],
    };
  }

  const version = (raw as Record<string, unknown>)["schema_version"];
  if (version !== SUPPORTED_ROBOT_SCHEMA_VERSION) {
    return {
      ok: false,
      config: null,
      diagnostics: [
        {
          path: "schema_version",
          message: `Unsupported schema_version "${String(version ?? "missing")}"; expected "${SUPPORTED_ROBOT_SCHEMA_VERSION}"`,
          line: 1,
          column: 1,
        },
      ],
    };
  }

  const parsed = robotConfigSchema.safeParse(raw);
  if (!parsed.success) {
    return {
      ok: false,
      config: null,
      diagnostics: parsed.error.issues.map((issue) => ({
        path: issue.path.length > 0 ? issue.path.join(".") : "<root>",
        message: issue.message,
        line: null,
        column: null,
      })),
    };
  }

  return { ok: true, config: parsed.data, diagnostics: [] };
}

/**
 * Updates `robot.yaml` while preserving existing YAML comments and formatting
 * via the `yaml` Document CST whenever `baseYaml` parses cleanly.
 */
export function patchRobotConfigYamlRoundTrip(
  baseYaml: string,
  nextConfig: RobotConfig,
): string {
  const validated = robotConfigSchema.parse(nextConfig);
  const doc = parseDocument(baseYaml);
  if (doc.errors.length > 0 || !doc.contents) {
    return stringifyYaml(validated);
  }

  doc.setIn(["schema_version"], validated.schema_version);
  doc.setIn(["robot", "id"], validated.robot.id);
  doc.setIn(["robot", "name"], validated.robot.name);
  doc.setIn(["robot", "version"], validated.robot.version);
  if (validated.robot.description !== undefined && validated.robot.description !== null) {
    doc.setIn(["robot", "description"], validated.robot.description);
  }
  doc.setIn(["runtime", "tick_rate_hz"], validated.runtime.tick_rate_hz);
  doc.setIn(["runtime", "log_level"], validated.runtime.log_level);
  doc.setIn(["runtime", "history_retention_days"], validated.runtime.history_retention_days);

  const normalizedComponents = validated.components.map((comp) => {
    const out: Record<string, unknown> = {
      id: comp.id,
      category: comp.category,
      model: comp.model,
    };
    if (comp.driver !== undefined && comp.driver !== null) out["driver"] = comp.driver;
    if (comp.depends_on.length > 0) out["depends_on"] = [...comp.depends_on];
    out["settings"] = { ...comp.settings };
    return out;
  });
  doc.setIn(["components"], normalizedComponents);
  return doc.toString();
}

export interface BuiltInModelSpec {
  readonly model: string;
  readonly label: string;
  readonly category: RuntimeComponentCategory;
  readonly defaultSettings: Readonly<Record<string, unknown>>;
  readonly capabilities: readonly string[];
}

export const BUILTIN_COMPONENT_CATALOG: readonly BuiltInModelSpec[] = [
  {
    model: "mock.motor",
    label: "Simulated / Mock Motor",
    category: "actuator",
    defaultSettings: { max_rpm: 300.0 },
    capabilities: ["can_set_velocity", "has_angular_position", "has_angular_velocity"],
  },
  {
    model: "mock.encoder",
    label: "Mock Wheel Encoder",
    category: "feedback",
    defaultSettings: { resolution: 4096 },
    capabilities: ["has_encoder_ticks", "has_angular_position", "has_angular_velocity"],
  },
  {
    model: "mock.imu",
    label: "Mock 9-DOF IMU",
    category: "spatial",
    defaultSettings: { sample_rate_hz: 100.0 },
    capabilities: [
      "has_orientation_quaternion",
      "has_angular_velocity_3d",
      "has_linear_acceleration_3d",
    ],
  },
  {
    model: "mock.camera",
    label: "Mock RGB Camera",
    category: "vision",
    defaultSettings: { width: 640, height: 480, fps: 30 },
    capabilities: ["can_stream_frames", "has_rgb_frame"],
  },
];

export interface DiffLine {
  readonly kind: "context" | "add" | "remove";
  readonly oldLine: number | null;
  readonly newLine: number | null;
  readonly text: string;
}

/**
 * Deterministic LCS line diff for Studio Configuration Diff View (M05).
 */
export function computeLineDiff(before: string, after: string): DiffLine[] {
  const a = before.split("\n");
  const b = after.split("\n");
  const n = a.length;
  const m = b.length;

  const dp: number[][] = Array.from({ length: n + 1 }, () => Array<number>(m + 1).fill(0));
  for (let i = n - 1; i >= 0; i -= 1) {
    for (let j = m - 1; j >= 0; j -= 1) {
      const row = dp[i];
      const nextRow = dp[i + 1];
      if (!row || !nextRow) continue;
      if (a[i] === b[j]) {
        row[j] = (nextRow[j + 1] ?? 0) + 1;
      } else {
        row[j] = Math.max(nextRow[j] ?? 0, row[j + 1] ?? 0);
      }
    }
  }

  const result: DiffLine[] = [];
  let i = 0;
  let j = 0;
  while (i < n && j < m) {
    if (a[i] === b[j]) {
      result.push({ kind: "context", oldLine: i + 1, newLine: j + 1, text: a[i] ?? "" });
      i += 1;
      j += 1;
    } else if ((dp[i + 1]?.[j] ?? 0) >= (dp[i]?.[j + 1] ?? 0)) {
      result.push({ kind: "remove", oldLine: i + 1, newLine: null, text: a[i] ?? "" });
      i += 1;
    } else {
      result.push({ kind: "add", oldLine: null, newLine: j + 1, text: b[j] ?? "" });
      j += 1;
    }
  }
  while (i < n) {
    result.push({ kind: "remove", oldLine: i + 1, newLine: null, text: a[i] ?? "" });
    i += 1;
  }
  while (j < m) {
    result.push({ kind: "add", oldLine: null, newLine: j + 1, text: b[j] ?? "" });
    j += 1;
  }
  return result;
}
