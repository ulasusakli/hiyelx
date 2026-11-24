import { useMemo, useState } from "react";
import { AlertTriangle, CheckCircle2, PlaySquare, Plus, ShieldCheck, Trash2 } from "lucide-react";
import type { RobotConfig } from "@hiyelx/config-engine";
import {
  WORKFLOW_ACTIONS,
  WORKFLOW_FAULT_POLICIES,
  serializeApplicationWorkflowYaml,
  validateWorkflowAgainstRobot,
  type ApplicationWorkflowDocument,
  type WorkflowFaultPolicy,
  type WorkflowTask,
} from "@hiyelx/workflow-engine";
import { StatusBadge } from "@hiyelx/ui";

export function ApplicationStudioView({
  workflow,
  robotConfig,
  onChangeWorkflow,
}: {
  readonly workflow: ApplicationWorkflowDocument;
  readonly robotConfig: RobotConfig | null;
  readonly onChangeWorkflow: (next: ApplicationWorkflowDocument) => void;
}) {
  const componentIds = useMemo(
    () => robotConfig?.components.map((comp) => comp.id) ?? [],
    [robotConfig],
  );
  const [taskName, setTaskName] = useState("Verify Motor Velocity");
  const [targetComponent, setTargetComponent] = useState(componentIds[0] ?? "");
  const [action, setAction] = useState<string>(WORKFLOW_ACTIONS[0]);
  const [timeoutMs, setTimeoutMs] = useState(2000);
  const [onFault, setOnFault] = useState<WorkflowFaultPolicy>("safe_stop");

  const resolvedTarget = componentIds.includes(targetComponent)
    ? targetComponent
    : (componentIds[0] ?? "");

  const issues = useMemo(
    () => validateWorkflowAgainstRobot(workflow, robotConfig),
    [workflow, robotConfig],
  );
  const yamlPreview = useMemo(() => serializeApplicationWorkflowYaml(workflow), [workflow]);

  function handleAddTask() {
    if (!resolvedTarget || taskName.trim().length === 0) return;
    let index = workflow.tasks.length + 1;
    let taskId = `task_${index}`;
    const existing = new Set(workflow.tasks.map((t) => t.id));
    while (existing.has(taskId)) {
      index += 1;
      taskId = `task_${index}`;
    }

    const nextTask: WorkflowTask = {
      id: taskId,
      name: taskName.trim(),
      target_component: resolvedTarget,
      action,
      parameters: {},
      timeout_ms: Math.max(100, timeoutMs),
      on_fault: onFault,
      next_tasks: [],
    };
    onChangeWorkflow({
      ...workflow,
      tasks: [...workflow.tasks, nextTask],
    });
  }

  function handleRemoveTask(taskId: string) {
    onChangeWorkflow({
      ...workflow,
      tasks: workflow.tasks
        .filter((t) => t.id !== taskId)
        .map((t) => ({
          ...t,
          next_tasks: t.next_tasks.filter((nxt) => nxt !== taskId),
        })),
    });
  }

  return (
    <section
      aria-label="Application Studio"
      className="grid min-h-0 flex-1 grid-cols-1 divide-y divide-slate-800 lg:grid-cols-12 lg:divide-x lg:divide-y-0"
    >
      <div className="flex min-h-0 flex-col overflow-y-auto bg-slate-950 p-4 lg:col-span-7">
        <div className="mb-4 flex flex-wrap items-center justify-between gap-2 border-b border-slate-800 pb-3">
          <div>
            <p className="text-[11px] font-bold tracking-wider text-cyan-400 uppercase">
              Application Studio · M07
            </p>
            <h2 className="mt-0.5 text-base font-semibold text-slate-100">
              {workflow.application.name}
            </h2>
          </div>

          {issues.length === 0 ? (
            <StatusBadge tone="success">
              <CheckCircle2 className="h-3.5 w-3.5" aria-hidden="true" />
              Workflow valid
            </StatusBadge>
          ) : (
            <StatusBadge tone="error">
              <AlertTriangle className="h-3.5 w-3.5" aria-hidden="true" />
              {issues.length} validation error(s)
            </StatusBadge>
          )}
        </div>

        <div className="mb-4 flex items-center gap-2 rounded-lg border border-cyan-900/60 bg-cyan-950/20 px-3 py-2 text-xs text-cyan-200">
          <ShieldCheck className="h-4 w-4 shrink-0 text-cyan-400" aria-hidden="true" />
          <span>
            Execution Boundary: Studio designs and validates <code>applications/main.yaml</code>;
            HIYELX Runtime executes tasks with RB-1 deadlines and best-effort safe-stop.
          </span>
        </div>

        {issues.length > 0 && (
          <div
            role="alert"
            className="mb-4 rounded-lg border border-rose-800/80 bg-rose-950/40 p-3 text-xs text-rose-200"
          >
            <ul className="list-disc space-y-1 pl-4 font-mono">
              {issues.map((issue, idx) => (
                <li key={idx}>{issue.message}</li>
              ))}
            </ul>
          </div>
        )}

        <div className="mb-4 rounded-xl border border-slate-800 bg-slate-900/50 p-3 text-xs">
          <p className="mb-2 font-semibold text-slate-300">Add Declarative Workflow Task</p>
          <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
            <input
              aria-label="Workflow task name"
              type="text"
              className="rounded border border-slate-700 bg-slate-950 px-2.5 py-1.5 text-xs text-slate-100"
              value={taskName}
              onChange={(event) => setTaskName(event.target.value)}
            />
            <select
              aria-label="Workflow target component"
              className="rounded border border-slate-700 bg-slate-950 px-2 py-1.5 font-mono text-xs text-slate-100"
              value={resolvedTarget}
              onChange={(event) => setTargetComponent(event.target.value)}
            >
              {componentIds.map((compId) => (
                <option key={compId} value={compId}>
                  {compId}
                </option>
              ))}
            </select>
            <select
              aria-label="Workflow task action"
              className="rounded border border-slate-700 bg-slate-950 px-2 py-1.5 font-mono text-xs text-slate-100"
              value={action}
              onChange={(event) => setAction(event.target.value)}
            >
              {WORKFLOW_ACTIONS.map((act) => (
                <option key={act} value={act}>
                  {act}
                </option>
              ))}
            </select>
            <div className="flex items-center gap-2">
              <input
                aria-label="Task timeout ms"
                type="number"
                min={100}
                step={100}
                className="w-24 rounded border border-slate-700 bg-slate-950 px-2 py-1.5 font-mono text-xs text-slate-100"
                value={timeoutMs}
                onChange={(event) => setTimeoutMs(Number(event.target.value) || 1000)}
              />
              <select
                aria-label="Task fault policy"
                className="flex-1 rounded border border-slate-700 bg-slate-950 px-2 py-1.5 font-mono text-xs text-slate-100"
                value={onFault}
                onChange={(event) => setOnFault(event.target.value as WorkflowFaultPolicy)}
              >
                {WORKFLOW_FAULT_POLICIES.map((policy) => (
                  <option key={policy} value={policy}>
                    on_fault: {policy}
                  </option>
                ))}
              </select>
            </div>
          </div>
          <button
            type="button"
            disabled={!resolvedTarget || taskName.trim().length === 0}
            className="mt-2.5 inline-flex items-center gap-1 rounded-md bg-cyan-600 px-3 py-1.5 font-semibold text-slate-950 hover:bg-cyan-500 disabled:bg-slate-800 disabled:text-slate-500"
            onClick={handleAddTask}
          >
            <Plus className="h-3.5 w-3.5" aria-hidden="true" />
            Add Workflow Task
          </button>
        </div>

        <ol className="space-y-2">
          {workflow.tasks.map((task, idx) => (
            <li
              key={task.id}
              className="rounded-xl border border-slate-800 bg-slate-900/50 p-3 text-xs"
            >
              <div className="flex items-center justify-between gap-2">
                <span className="inline-flex items-center gap-2 font-semibold text-slate-100">
                  <PlaySquare className="h-3.5 w-3.5 text-cyan-400" aria-hidden="true" />
                  {idx + 1}. {task.name}
                </span>
                <button
                  type="button"
                  aria-label={`Remove task ${task.id}`}
                  className="inline-flex items-center gap-1 rounded border border-rose-900/70 px-2 py-0.5 text-rose-300 hover:bg-rose-950/60"
                  onClick={() => handleRemoveTask(task.id)}
                >
                  <Trash2 className="h-3 w-3" aria-hidden="true" />
                  Remove
                </button>
              </div>
              <p className="mt-1 font-mono text-slate-400">
                id: {task.id} · target: <span className="text-cyan-300">{task.target_component}</span>{" "}
                · action: <span className="text-emerald-300">{task.action}</span>
              </p>
              <p className="mt-0.5 font-mono text-[11px] text-slate-500">
                timeout: {task.timeout_ms} ms · on_fault: {task.on_fault}
              </p>
            </li>
          ))}
        </ol>
      </div>

      <div className="flex min-h-0 flex-col bg-slate-900/40 p-4 lg:col-span-5">
        <p className="mb-2 font-mono text-xs text-slate-300">
          applications/main.yaml (Declarative Preview · schema v1)
        </p>
        <pre
          aria-label="applications/main.yaml preview"
          className="min-h-0 flex-1 overflow-auto rounded-xl border border-slate-800 bg-slate-950 p-3 font-mono text-xs text-slate-200"
        >
          {yamlPreview}
        </pre>
      </div>
    </section>
  );
}
