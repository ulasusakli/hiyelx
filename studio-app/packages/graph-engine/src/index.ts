import ELK from "elkjs/lib/elk.bundled.js";
import { parse as parseYaml, stringify as stringifyYaml } from "yaml";
import { z } from "zod";

export const SUPPORTED_GRAPH_SCHEMA_VERSION = "1" as const;

export const STUDIO_NODE_KINDS = [
  "hardware",
  "sensor",
  "actuator",
  "controller",
  "runtime_component",
  "communication",
  "application",
  "safety",
] as const;

export const RUNTIME_COMPONENT_CATEGORIES = [
  "actuator",
  "vision",
  "spatial",
  "feedback",
  "service",
] as const;

export const STUDIO_EDGE_KINDS = [
  "data",
  "command",
  "feedback",
  "dependency",
  "physical_connection",
] as const;

export type StudioNodeKind = (typeof STUDIO_NODE_KINDS)[number];
export type RuntimeComponentCategory = (typeof RUNTIME_COMPONENT_CATEGORIES)[number];
export type StudioEdgeKind = (typeof STUDIO_EDGE_KINDS)[number];

const nonBlankString = z.string().refine((v) => v.trim().length > 0, "Must not be blank");

export const graphNodeSchema = z
  .object({
    id: nonBlankString,
    kind: z.enum(STUDIO_NODE_KINDS),
    label: nonBlankString,
    component_id: nonBlankString.nullable().optional(),
    category: z.enum(RUNTIME_COMPONENT_CATEGORIES).nullable().optional(),
    model: nonBlankString.nullable().optional(),
  })
  .strict();

export const graphEdgeSchema = z
  .object({
    id: nonBlankString,
    source: nonBlankString,
    target: nonBlankString,
    kind: z.enum(STUDIO_EDGE_KINDS),
    source_port: z.string().nullable().optional(),
    target_port: z.string().nullable().optional(),
    topic: z.string().nullable().optional(),
  })
  .strict();

export const robotGraphDocumentSchema = z
  .object({
    schema_version: z.literal(SUPPORTED_GRAPH_SCHEMA_VERSION),
    nodes: z.array(graphNodeSchema).default([]),
    edges: z.array(graphEdgeSchema).default([]),
  })
  .strict()
  .superRefine((graph, ctx) => {
    const nodeIds = new Set<string>();
    for (const [index, node] of graph.nodes.entries()) {
      if (nodeIds.has(node.id)) {
        ctx.addIssue({
          code: z.ZodIssueCode.custom,
          path: ["nodes", index, "id"],
          message: `Duplicate graph node id "${node.id}"`,
        });
      }
      nodeIds.add(node.id);
    }

    const edgeIds = new Set<string>();
    for (const [index, edge] of graph.edges.entries()) {
      if (edgeIds.has(edge.id)) {
        ctx.addIssue({
          code: z.ZodIssueCode.custom,
          path: ["edges", index, "id"],
          message: `Duplicate graph edge id "${edge.id}"`,
        });
      }
      edgeIds.add(edge.id);
      if (!nodeIds.has(edge.source)) {
        ctx.addIssue({
          code: z.ZodIssueCode.custom,
          path: ["edges", index, "source"],
          message: `Edge "${edge.id}" references unknown source node "${edge.source}"`,
        });
      }
      if (!nodeIds.has(edge.target)) {
        ctx.addIssue({
          code: z.ZodIssueCode.custom,
          path: ["edges", index, "target"],
          message: `Edge "${edge.id}" references unknown target node "${edge.target}"`,
        });
      }
      if (edge.kind === "dependency" && edge.source === edge.target) {
        ctx.addIssue({
          code: z.ZodIssueCode.custom,
          path: ["edges", index],
          message: `Dependency edge "${edge.id}" cannot target itself ("${edge.source}")`,
        });
      }
    }
  });

export type GraphNode = z.infer<typeof graphNodeSchema>;
export type GraphEdge = z.infer<typeof graphEdgeSchema>;
export type RobotGraphDocument = z.infer<typeof robotGraphDocumentSchema>;

export type DependencyDagValidationResult =
  | { readonly ok: true; readonly order: readonly string[] }
  | { readonly ok: false; readonly cycle: readonly string[]; readonly message: string };

/**
 * Validates that lifecycle `dependency` edges form an acyclic DAG while permitting
 * closed-loop cycles on `data`, `command`, `feedback`, and `physical_connection` edges.
 */
export function validateDependencyDag(graph: RobotGraphDocument): DependencyDagValidationResult {
  const nodeIds = graph.nodes.map((node) => node.id).sort();
  const prerequisites = new Map<string, Set<string>>();
  const dependents = new Map<string, Set<string>>();
  for (const id of nodeIds) {
    prerequisites.set(id, new Set());
    dependents.set(id, new Set());
  }

  for (const edge of graph.edges) {
    if (edge.kind !== "dependency") continue;
    prerequisites.get(edge.target)?.add(edge.source);
    dependents.get(edge.source)?.add(edge.target);
  }

  const indegree = new Map<string, number>();
  const ready: string[] = [];
  for (const id of nodeIds) {
    const degree = prerequisites.get(id)?.size ?? 0;
    indegree.set(id, degree);
    if (degree === 0) ready.push(id);
  }
  ready.sort();

  const order: string[] = [];
  while (ready.length > 0) {
    const current = ready.shift();
    if (current === undefined) break;
    order.push(current);
    const nextNodes = [...(dependents.get(current) ?? [])].sort();
    for (const next of nextNodes) {
      const updated = (indegree.get(next) ?? 0) - 1;
      indegree.set(next, updated);
      if (updated === 0) {
        ready.push(next);
        ready.sort();
      }
    }
  }

  if (order.length !== nodeIds.length) {
    const unresolved = new Set<string>(
      nodeIds.filter((id) => (indegree.get(id) ?? 0) > 0),
    );
    const cycle = findDirectedCycle(dependents, unresolved);
    return {
      ok: false,
      cycle,
      message: `Dependency cycle detected: ${cycle.join(" -> ")}`,
    };
  }

  return { ok: true, order };
}

function findDirectedCycle(
  adjacency: Map<string, Set<string>>,
  unresolved: Set<string>,
): string[] {
  const visited = new Set<string>();
  const activeIndex = new Map<string, number>();
  const stack: string[] = [];

  function dfs(nodeId: string): string[] | null {
    const existing = activeIndex.get(nodeId);
    if (existing !== undefined) {
      return [...stack.slice(existing), nodeId];
    }
    if (visited.has(nodeId)) return null;

    activeIndex.set(nodeId, stack.length);
    stack.push(nodeId);
    for (const next of [...(adjacency.get(nodeId) ?? [])].sort()) {
      if (!unresolved.has(next)) continue;
      const found = dfs(next);
      if (found !== null) return found;
    }
    stack.pop();
    activeIndex.delete(nodeId);
    visited.add(nodeId);
    return null;
  }

  for (const id of [...unresolved].sort()) {
    const found = dfs(id);
    if (found !== null) return found;
  }
  return [...unresolved].sort();
}

export function projectDependsOn(graph: RobotGraphDocument): Record<string, string[]> {
  const nodeToComponent = new Map<string, string>();
  const projected = new Map<string, Set<string>>();

  for (const node of graph.nodes) {
    if (node.component_id) {
      nodeToComponent.set(node.id, node.component_id);
      projected.set(node.component_id, new Set());
    }
  }

  for (const edge of graph.edges) {
    if (edge.kind !== "dependency") continue;
    const sourceComp = nodeToComponent.get(edge.source);
    const targetComp = nodeToComponent.get(edge.target);
    if (sourceComp !== undefined && targetComp !== undefined) {
      projected.get(targetComp)?.add(sourceComp);
    }
  }

  const result: Record<string, string[]> = {};
  for (const [compId, deps] of [...projected.entries()].sort(([a], [b]) => a.localeCompare(b))) {
    result[compId] = [...deps].sort();
  }
  return result;
}

export function parseRobotGraphYaml(source: string): RobotGraphDocument {
  const raw: unknown = parseYaml(source);
  return robotGraphDocumentSchema.parse(raw);
}

export function serializeRobotGraphYaml(graph: RobotGraphDocument): string {
  return stringifyYaml(robotGraphDocumentSchema.parse(graph));
}

export interface AutoLayoutPosition {
  readonly x: number;
  readonly y: number;
}

/**
 * Computes visual node coordinates via ELK.js strictly as a layout engine
 * (does not impose DAG constraints on feedback or data edges).
 */
export async function computeAutoLayout(
  graph: RobotGraphDocument,
): Promise<Record<string, AutoLayoutPosition>> {
  if (graph.nodes.length === 0) return {};

  const elk = new ELK();
  const layouted = await elk.layout({
    id: "root",
    layoutOptions: {
      "elk.algorithm": "layered",
      "elk.direction": "RIGHT",
      "elk.spacing.nodeNode": "60",
      "elk.layered.spacing.nodeNodeBetweenLayers": "120",
    },
    children: graph.nodes.map((node) => ({
      id: node.id,
      width: 210,
      height: 88,
    })),
    edges: graph.edges.map((edge) => ({
      id: edge.id,
      sources: [edge.source],
      targets: [edge.target],
    })),
  });

  const positions: Record<string, AutoLayoutPosition> = {};
  for (const child of layouted.children ?? []) {
    positions[child.id] = {
      x: Math.round(child.x ?? 0),
      y: Math.round(child.y ?? 0),
    };
  }
  return positions;
}
