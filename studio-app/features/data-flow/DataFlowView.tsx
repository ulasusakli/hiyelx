import { useMemo, useState } from "react";
import { ArrowRight, Plus, RefreshCw, Trash2, Waves } from "lucide-react";
import type { RobotGraphDocument, StudioEdgeKind } from "@hiyelx/graph-engine";
import { StatusBadge } from "@hiyelx/ui";

type FlowEdgeKind = Extract<StudioEdgeKind, "data" | "command" | "feedback">;
const FLOW_EDGE_KINDS: readonly FlowEdgeKind[] = ["data", "command", "feedback"];

export function DataFlowView({
  graph,
  liveSamplingHz,
  latestSequence,
  onAddFlowEdge,
  onRemoveFlowEdge,
}: {
  readonly graph: RobotGraphDocument;
  readonly liveSamplingHz: number | null;
  readonly latestSequence: number | null;
  readonly onAddFlowEdge: (
    source: string,
    target: string,
    kind: FlowEdgeKind,
    topic: string,
  ) => void;
  readonly onRemoveFlowEdge: (edgeId: string) => void;
}) {
  const [mode, setMode] = useState<"design" | "live">("design");
  const [source, setSource] = useState<string>(graph.nodes[0]?.id ?? "");
  const [target, setTarget] = useState<string>(graph.nodes[1]?.id ?? graph.nodes[0]?.id ?? "");
  const [kind, setKind] = useState<FlowEdgeKind>("data");
  const [topic, setTopic] = useState("robot/topic");

  const flowEdges = useMemo(
    () =>
      graph.edges.filter(
        (edge) => edge.kind === "data" || edge.kind === "command" || edge.kind === "feedback",
      ),
    [graph.edges],
  );

  const hasFeedbackLoop = useMemo(
    () => flowEdges.some((edge) => edge.kind === "feedback"),
    [flowEdges],
  );

  const resolvedSource = graph.nodes.some((n) => n.id === source)
    ? source
    : (graph.nodes[0]?.id ?? "");
  const resolvedTarget = graph.nodes.some((n) => n.id === target)
    ? target
    : (graph.nodes[1]?.id ?? graph.nodes[0]?.id ?? "");

  return (
    <section
      aria-label="Connection and Data Flow Designer"
      className="flex min-h-0 flex-1 flex-col overflow-y-auto bg-slate-950 p-4"
    >
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3 border-b border-slate-800 pb-3">
        <div>
          <p className="text-[11px] font-bold tracking-wider text-cyan-400 uppercase">
            Connection &amp; Data Flow Designer · M06
          </p>
          <h2 className="mt-0.5 text-base font-semibold text-slate-100">
            Topics, Commands &amp; Closed-Loop Feedback Channels
          </h2>
        </div>

        <div className="flex items-center gap-2">
          {hasFeedbackLoop && (
            <StatusBadge tone="success">
              <RefreshCw className="h-3 w-3" aria-hidden="true" />
              Closed-loop feedback active (non-DAG valid)
            </StatusBadge>
          )}
          <button
            type="button"
            className={`rounded-md border px-2.5 py-1 text-xs ${
              mode === "design"
                ? "border-cyan-500 bg-slate-800 text-cyan-300"
                : "border-slate-700 bg-slate-950 text-slate-400"
            }`}
            onClick={() => setMode("design")}
          >
            Design Mode
          </button>
          <button
            type="button"
            className={`rounded-md border px-2.5 py-1 text-xs ${
              mode === "live"
                ? "border-emerald-500 bg-slate-800 text-emerald-300"
                : "border-slate-700 bg-slate-950 text-slate-400"
            }`}
            onClick={() => setMode("live")}
          >
            Live Overlay
          </button>
        </div>
      </div>

      <div className="mb-4 rounded-xl border border-slate-800 bg-slate-900/50 p-3 text-xs">
        <p className="mb-2 font-semibold text-slate-300">Add Data / Command / Feedback Channel</p>
        <div className="flex flex-wrap items-center gap-2">
          <select
            aria-label="Flow source node"
            className="rounded border border-slate-700 bg-slate-950 px-2 py-1.5 font-mono text-xs text-slate-100"
            value={resolvedSource}
            onChange={(event) => setSource(event.target.value)}
          >
            {graph.nodes.map((node) => (
              <option key={node.id} value={node.id}>
                {node.id}
              </option>
            ))}
          </select>

          <ArrowRight className="h-3.5 w-3.5 text-slate-500" aria-hidden="true" />

          <select
            aria-label="Flow target node"
            className="rounded border border-slate-700 bg-slate-950 px-2 py-1.5 font-mono text-xs text-slate-100"
            value={resolvedTarget}
            onChange={(event) => setTarget(event.target.value)}
          >
            {graph.nodes.map((node) => (
              <option key={node.id} value={node.id}>
                {node.id}
              </option>
            ))}
          </select>

          <select
            aria-label="Flow edge kind"
            className="rounded border border-slate-700 bg-slate-950 px-2 py-1.5 font-mono text-xs text-slate-100"
            value={kind}
            onChange={(event) => setKind(event.target.value as FlowEdgeKind)}
          >
            {FLOW_EDGE_KINDS.map((edgeKind) => (
              <option key={edgeKind} value={edgeKind}>
                {edgeKind}
              </option>
            ))}
          </select>

          <input
            aria-label="Channel topic name"
            type="text"
            className="min-w-[160px] flex-1 rounded border border-slate-700 bg-slate-950 px-2.5 py-1.5 font-mono text-xs text-slate-100"
            placeholder="topic/name"
            value={topic}
            onChange={(event) => setTopic(event.target.value)}
          />

          <button
            type="button"
            disabled={!resolvedSource || !resolvedTarget || topic.trim().length === 0}
            className="inline-flex items-center gap-1 rounded-md bg-cyan-600 px-3 py-1.5 font-semibold text-slate-950 hover:bg-cyan-500 disabled:bg-slate-800 disabled:text-slate-500"
            onClick={() => {
              onAddFlowEdge(resolvedSource, resolvedTarget, kind, topic.trim());
            }}
          >
            <Plus className="h-3.5 w-3.5" aria-hidden="true" />
            Add Channel
          </button>
        </div>
      </div>

      <div className="rounded-xl border border-slate-800 bg-slate-900/40 p-3">
        <div className="mb-2 flex items-center justify-between text-xs">
          <span className="inline-flex items-center gap-1.5 font-semibold text-slate-300">
            <Waves className="h-3.5 w-3.5 text-cyan-400" aria-hidden="true" />
            Active Data Flow Channels ({flowEdges.length})
          </span>
          {mode === "live" && (
            <span className="font-mono text-emerald-300">
              {liveSamplingHz !== null
                ? `Live stream: ${liveSamplingHz.toFixed(1)} Hz · seq #${latestSequence ?? 0}`
                : "No live SSE stream active"}
            </span>
          )}
        </div>

        {flowEdges.length === 0 ? (
          <p className="py-6 text-center text-xs text-slate-400">
            No data, command, or feedback edges defined yet.
          </p>
        ) : (
          <ul className="space-y-2 font-mono text-xs">
            {flowEdges.map((edge) => (
              <li
                key={edge.id}
                className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-slate-800 bg-slate-950 p-2.5"
              >
                <div className="flex flex-wrap items-center gap-2">
                  <StatusBadge
                    tone={
                      edge.kind === "feedback"
                        ? "warning"
                        : edge.kind === "data"
                          ? "success"
                          : "neutral"
                    }
                  >
                    {edge.kind}
                  </StatusBadge>
                  <span className="text-slate-100">{edge.source}</span>
                  <ArrowRight className="h-3 w-3 text-slate-500" aria-hidden="true" />
                  <span className="text-slate-100">{edge.target}</span>
                  {edge.topic && (
                    <span className="rounded bg-slate-800 px-1.5 py-0.5 text-cyan-300">
                      {edge.topic}
                    </span>
                  )}
                </div>

                <button
                  type="button"
                  aria-label={`Remove channel ${edge.id}`}
                  className="inline-flex items-center gap-1 rounded border border-rose-900/70 px-2 py-0.5 text-rose-300 hover:bg-rose-950/60"
                  onClick={() => onRemoveFlowEdge(edge.id)}
                >
                  <Trash2 className="h-3 w-3" aria-hidden="true" />
                  Remove
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>
    </section>
  );
}
