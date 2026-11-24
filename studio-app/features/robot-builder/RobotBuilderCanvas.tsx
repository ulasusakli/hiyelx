import { useMemo } from "react";
import {
  Background,
  Controls,
  ReactFlow,
  type Connection,
  type Edge,
  type Node,
} from "@xyflow/react";
import { Cpu, GitBranch, LayoutGrid, Plus, Trash2 } from "lucide-react";
import {
  BUILTIN_COMPONENT_CATALOG,
  type BuiltInModelSpec,
} from "@hiyelx/config-engine";
import {
  STUDIO_EDGE_KINDS,
  validateDependencyDag,
  type GraphNode,
  type RobotGraphDocument,
  type StudioEdgeKind,
} from "@hiyelx/graph-engine";
import type { CanvasLayoutDocument } from "@hiyelx/project-engine";
import { StatusBadge } from "@hiyelx/ui";

const EDGE_COLORS: Record<StudioEdgeKind, string> = {
  dependency: "#38bdf8",
  data: "#34d399",
  command: "#f59e0b",
  feedback: "#f472b6",
  physical_connection: "#94a3b8",
};

export function RobotBuilderCanvas({
  graph,
  layout,
  selectedNodeId,
  activeEdgeKind,
  onSelectNode,
  onChangeEdgeKind,
  onAddComponent,
  onDeleteSelectedNode,
  onConnectEdge,
  onAutoLayout,
}: {
  readonly graph: RobotGraphDocument;
  readonly layout: CanvasLayoutDocument;
  readonly selectedNodeId: string | null;
  readonly activeEdgeKind: StudioEdgeKind;
  readonly onSelectNode: (nodeId: string | null) => void;
  readonly onChangeEdgeKind: (kind: StudioEdgeKind) => void;
  readonly onAddComponent: (spec: BuiltInModelSpec) => void;
  readonly onDeleteSelectedNode: () => void;
  readonly onConnectEdge: (source: string, target: string, kind: StudioEdgeKind) => void;
  readonly onAutoLayout: () => void;
}) {
  const dagValidation = useMemo(() => validateDependencyDag(graph), [graph]);

  const rfNodes: Node[] = useMemo(
    () =>
      graph.nodes.map((node: GraphNode, index) => {
        const pos = layout.positions[node.id] ?? { x: 80 + index * 220, y: 120 };
        const isSelected = node.id === selectedNodeId;
        return {
          id: node.id,
          position: pos,
          selected: isSelected,
          data: {
            label: `${node.label} (${node.model ?? node.kind})`,
          },
          style: {
            background: isSelected ? "#0f172a" : "#111827",
            color: "#f8fafc",
            border: isSelected ? "2px solid #22d3ee" : "1px solid #334155",
            borderRadius: "10px",
            padding: "8px 12px",
            fontSize: "12px",
            width: 210,
          },
        };
      }),
    [graph.nodes, layout.positions, selectedNodeId],
  );

  const rfEdges: Edge[] = useMemo(
    () =>
      graph.edges.map((edge) => ({
        id: edge.id,
        source: edge.source,
        target: edge.target,
        label: edge.topic ? `${edge.kind}: ${edge.topic}` : edge.kind,
        animated: edge.kind === "feedback" || edge.kind === "data",
        style: {
          stroke: EDGE_COLORS[edge.kind],
          strokeDasharray: edge.kind === "feedback" ? "5 4" : undefined,
        },
        labelStyle: { fill: "#cbd5e1", fontSize: 10 },
      })),
    [graph.edges],
  );

  const isJsdom = typeof navigator !== "undefined" && navigator.userAgent.includes("jsdom");

  function handleConnect(connection: Connection) {
    if (connection.source && connection.target) {
      onConnectEdge(connection.source, connection.target, activeEdgeKind);
    }
  }

  return (
    <section aria-label="Visual Robot Builder" className="flex min-h-0 flex-1 flex-col">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-slate-800 bg-slate-900/60 px-4 py-2">
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-xs font-semibold text-slate-400">Add component:</span>
          {BUILTIN_COMPONENT_CATALOG.map((spec) => (
            <button
              key={spec.model}
              type="button"
              className="inline-flex items-center gap-1 rounded-md border border-slate-700 bg-slate-950 px-2 py-1 font-mono text-xs text-slate-200 hover:border-cyan-500/60 hover:bg-slate-800"
              onClick={() => onAddComponent(spec)}
            >
              <Plus className="h-3 w-3 text-cyan-400" aria-hidden="true" />
              {spec.model}
            </button>
          ))}
        </div>

        <div className="flex items-center gap-2">
          <label htmlFor="edge-kind-select" className="text-xs text-slate-400">
            Edge type
          </label>
          <select
            id="edge-kind-select"
            className="rounded border border-slate-700 bg-slate-950 px-2 py-1 text-xs text-slate-100"
            value={activeEdgeKind}
            onChange={(event) => onChangeEdgeKind(event.target.value as StudioEdgeKind)}
          >
            {STUDIO_EDGE_KINDS.map((kind) => (
              <option key={kind} value={kind}>
                {kind}
              </option>
            ))}
          </select>

          <button
            type="button"
            className="inline-flex items-center gap-1 rounded-md border border-slate-700 bg-slate-950 px-2.5 py-1 text-xs text-slate-200 hover:bg-slate-800"
            onClick={onAutoLayout}
          >
            <LayoutGrid className="h-3.5 w-3.5" aria-hidden="true" />
            Auto-Layout (ELK)
          </button>

          <button
            type="button"
            disabled={selectedNodeId === null}
            className="inline-flex items-center gap-1 rounded-md border border-rose-800/70 bg-rose-950/50 px-2.5 py-1 text-xs text-rose-200 disabled:opacity-40"
            onClick={onDeleteSelectedNode}
          >
            <Trash2 className="h-3.5 w-3.5" aria-hidden="true" />
            Remove node
          </button>
        </div>
      </div>

      <div className="flex items-center justify-between border-b border-slate-800 bg-slate-950/70 px-4 py-1.5 text-xs">
        <div className="flex items-center gap-2">
          <GitBranch className="h-3.5 w-3.5 text-cyan-400" aria-hidden="true" />
          <span className="text-slate-300">
            General Graph (non-DAG feedback allowed · {graph.nodes.length} nodes ·{" "}
            {graph.edges.length} edges)
          </span>
        </div>
        {dagValidation.ok ? (
          <StatusBadge tone="success">Lifecycle depends_on DAG valid</StatusBadge>
        ) : (
          <StatusBadge tone="error">{dagValidation.message}</StatusBadge>
        )}
      </div>

      <div className="relative min-h-[340px] flex-1 bg-slate-950">
        {isJsdom ? (
          <div className="grid grid-cols-2 gap-3 p-4" data-testid="robot-builder-node-list">
            {graph.nodes.map((node) => (
              <button
                key={node.id}
                type="button"
                className={`rounded-lg border p-3 text-left ${
                  node.id === selectedNodeId
                    ? "border-cyan-400 bg-slate-900"
                    : "border-slate-800 bg-slate-900/60"
                }`}
                onClick={() => onSelectNode(node.id)}
              >
                <div className="flex items-center justify-between">
                  <span className="inline-flex items-center gap-1.5 font-semibold text-slate-100">
                    <Cpu className="h-3.5 w-3.5 text-cyan-400" aria-hidden="true" />
                    {node.label}
                  </span>
                  <span className="font-mono text-xs text-slate-400">{node.kind}</span>
                </div>
                <p className="mt-1 font-mono text-xs text-slate-400">
                  {node.model ?? "structural node"}
                </p>
              </button>
            ))}
          </div>
        ) : (
          <ReactFlow
            nodes={rfNodes}
            edges={rfEdges}
            fitView
            onNodeClick={(_event, node) => onSelectNode(node.id)}
            onPaneClick={() => onSelectNode(null)}
            onConnect={handleConnect}
          >
            <Background color="#1e293b" gap={20} />
            <Controls />
          </ReactFlow>
        )}
      </div>
    </section>
  );
}
