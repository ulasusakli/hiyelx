import { parse as parseYaml, stringify as stringifyYaml } from "yaml";
import { z } from "zod";
import type { RobotConfig } from "@hiyelx/config-engine";

export const SUPPORTED_WORKFLOW_SCHEMA_VERSION = "1" as const;

export const WORKFLOW_FAULT_POLICIES = ["safe_stop", "abort", "degrade"] as const;
export type WorkflowFaultPolicy = (typeof WORKFLOW_FAULT_POLICIES)[number];

export const WORKFLOW_ACTIONS = [
  "read_state",
  "set_velocity",
  "set_position",
  "capture_frame",
  "wait",
  "safe_stop",
] as const;

const nonBlank = z.string().refine((v) => v.trim().length > 0, "Field must not be blank");

export const applicationMetadataSchema = z
  .object({
    id: nonBlank,
    name: nonBlank,
    version: nonBlank.default("0.1.0"),
    description: z.string().nullable().optional(),
  })
  .strict();

export const workflowTaskSchema = z
  .object({
    id: nonBlank,
    name: nonBlank,
    target_component: nonBlank,
    action: nonBlank,
    parameters: z.record(z.string(), z.unknown()).default({}),
    timeout_ms: z.number().int().positive().default(3000),
    on_fault: z.enum(WORKFLOW_FAULT_POLICIES).default("safe_stop"),
    next_tasks: z.array(nonBlank).default([]),
  })
  .strict();

export const applicationWorkflowSchema = z
  .object({
    schema_version: z.literal(SUPPORTED_WORKFLOW_SCHEMA_VERSION),
    application: applicationMetadataSchema,
    tasks: z.array(workflowTaskSchema).default([]),
  })
  .strict()
  .superRefine((doc, ctx) => {
    const ids = new Set<string>();
    for (const [index, task] of doc.tasks.entries()) {
      if (ids.has(task.id)) {
        ctx.addIssue({
          code: z.ZodIssueCode.custom,
          path: ["tasks", index, "id"],
          message: `Duplicate workflow task id "${task.id}"`,
        });
      }
      ids.add(task.id);
    }
    for (const [index, task] of doc.tasks.entries()) {
      for (const nextId of task.next_tasks) {
        if (nextId === task.id) {
          ctx.addIssue({
            code: z.ZodIssueCode.custom,
            path: ["tasks", index, "next_tasks"],
            message: `Task "${task.id}" cannot transition directly to itself`,
          });
        } else if (!ids.has(nextId)) {
          ctx.addIssue({
            code: z.ZodIssueCode.custom,
            path: ["tasks", index, "next_tasks"],
            message: `Task "${task.id}" references unknown next task "${nextId}"`,
          });
        }
      }
    }
  });

export type WorkflowTask = z.infer<typeof workflowTaskSchema>;
export type ApplicationWorkflowDocument = z.infer<typeof applicationWorkflowSchema>;

export interface WorkflowValidationIssue {
  readonly taskId: string | null;
  readonly message: string;
}

export function parseApplicationWorkflowYaml(source: string): ApplicationWorkflowDocument {
  const raw: unknown = parseYaml(source);
  if (raw === null || typeof raw !== "object" || Array.isArray(raw)) {
    throw new Error("Workflow root must be a YAML mapping");
  }
  const version = (raw as Record<string, unknown>)["schema_version"];
  if (version !== SUPPORTED_WORKFLOW_SCHEMA_VERSION) {
    throw new Error(
      `Unsupported workflow schema_version "${String(version ?? "missing")}"; expected "${SUPPORTED_WORKFLOW_SCHEMA_VERSION}"`,
    );
  }
  return applicationWorkflowSchema.parse(raw);
}

export function serializeApplicationWorkflowYaml(doc: ApplicationWorkflowDocument): string {
  return stringifyYaml(applicationWorkflowSchema.parse(doc));
}

export function validateWorkflowAgainstRobot(
  workflow: ApplicationWorkflowDocument,
  robotConfig: RobotConfig | null,
): readonly WorkflowValidationIssue[] {
  if (robotConfig === null) {
    return [{ taskId: null, message: "Cannot cross-validate workflow while robot.yaml is invalid." }];
  }
  const knownIds = new Set(robotConfig.components.map((c) => c.id));
  const issues: WorkflowValidationIssue[] = [];
  for (const task of workflow.tasks) {
    if (!knownIds.has(task.target_component)) {
      issues.push({
        taskId: task.id,
        message: `Task "${task.id}" targets unknown robot component "${task.target_component}".`,
      });
    }
  }
  return issues;
}

export function createStarterWorkflow(robotConfig: RobotConfig | null): ApplicationWorkflowDocument {
  const firstMotor =
    robotConfig?.components.find((c) => c.category === "actuator")?.id ??
    robotConfig?.components[0]?.id ??
    "drive_motor";
  const firstSensor =
    robotConfig?.components.find((c) => c.category === "feedback" || c.category === "vision")?.id ??
    firstMotor;

  return applicationWorkflowSchema.parse({
    schema_version: "1",
    application: {
      id: "main-inspection",
      name: "Simulated Sensor & Drive Check",
      version: "0.1.0",
      description: "Declarative multi-component workflow executed by HIYELX Runtime.",
    },
    tasks: [
      {
        id: "step_read_sensor",
        name: "Read Initial Sensor State",
        target_component: firstSensor,
        action: "read_state",
        parameters: {},
        timeout_ms: 1000,
        on_fault: "abort",
        next_tasks: ["step_command_motor"],
      },
      {
        id: "step_command_motor",
        name: "Command Safe Test Velocity",
        target_component: firstMotor,
        action: "set_velocity",
        parameters: { velocity_rad_s: 0.5 },
        timeout_ms: 2000,
        on_fault: "safe_stop",
        next_tasks: ["step_safe_stop"],
      },
      {
        id: "step_safe_stop",
        name: "Command Best-Effort Safe Stop",
        target_component: firstMotor,
        action: "safe_stop",
        parameters: {},
        timeout_ms: 1000,
        on_fault: "safe_stop",
        next_tasks: [],
      },
    ],
  });
}
