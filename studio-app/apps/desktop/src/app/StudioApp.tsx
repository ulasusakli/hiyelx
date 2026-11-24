import { useMemo, useState } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { Code2, Command, GitCompare, Network, Save } from "lucide-react";
import {
  patchRobotConfigYamlRoundTrip,
  validateRobotConfigYaml,
  type BuiltInModelSpec,
  type RobotConfig,
} from "@hiyelx/config-engine";
import {
  computeAutoLayout,
  parseRobotGraphYaml,
  projectDependsOn,
  validateDependencyDag,
  type RobotGraphDocument,
  type StudioEdgeKind,
  type StudioNodeKind,
} from "@hiyelx/graph-engine";
import {
  createStarterProjectSnapshot,
  type CanvasLayoutDocument,
  type ProjectManifest,
  type StarterTemplate,
} from "@hiyelx/project-engine";
import { StatusBadge } from "@hiyelx/ui";
import { ConfigEditorView } from "../../../../features/configuration/ConfigEditorView.tsx";
import { DiffPanel } from "../../../../features/configuration/DiffPanel.tsx";
import { ProjectSidebar } from "../../../../features/projects/ProjectSidebar.tsx";
import { RobotBuilderCanvas } from "../../../../features/robot-builder/RobotBuilderCanvas.tsx";
import { CommandPalette, type PaletteCommand } from "../../../../features/shell/CommandPalette.tsx";
import { useStudioUiStore, type StudioViewId } from "../../../../features/shell/uiStore.ts";

const queryClient = new QueryClient();

function nodeKindForCategory(category: BuiltInModelSpec["category"]): StudioNodeKind {
  if (category === "actuator") return "actuator";
  if (category === "service") return "runtime_component";
  return "sensor";
}

function StudioWorkbench() {
  const initialBundle = useMemo(
    () => createStarterProjectSnapshot("canonical-mock-rover", "hiyelx-rover-01", "HIYELX Canonical Rover"),
    [],
  );

  // Project document state represents the loaded filesystem workspace (saved vs working buffer).
  const [manifest, setManifest] = useState<ProjectManifest>(initialBundle.manifest);
  const [savedRobotYaml, setSavedRobotYaml] = useState<string>(initialBundle.robotYaml);
  const [workingRobotYaml, setWorkingRobotYaml] = useState<string>(initialBundle.robotYaml);
  const [graph, setGraph] = useState<RobotGraphDocument>(() =>
    parseRobotGraphYaml(initialBundle.graphYaml),
  );
  const [layout, setLayout] = useState<CanvasLayoutDocument>(initialBundle.layout);

  // Transient UI state lives exclusively in Zustand.
  const activeView = useStudioUiStore((s) => s.activeView);
  const activeProfile = useStudioUiStore((s) => s.activeProfile);
  const selectedNodeId = useStudioUiStore((s) => s.selectedNodeId);
  const activeEdgeKind = useStudioUiStore((s) => s.activeEdgeKind);
  const commandPaletteOpen = useStudioUiStore((s) => s.commandPaletteOpen);
  const setActiveView = useStudioUiStore((s) => s.setActiveView);
  const setActiveProfile = useStudioUiStore((s) => s.setActiveProfile);
  const setSelectedNodeId = useStudioUiStore((s) => s.setSelectedNodeId);
  const setActiveEdgeKind = useStudioUiStore((s) => s.setActiveEdgeKind);
  const setCommandPaletteOpen = useStudioUiStore((s) => s.setCommandPaletteOpen);

  const validation = useMemo(() => validateRobotConfigYaml(workingRobotYaml), [workingRobotYaml]);
  const dagValidation = useMemo(() => validateDependencyDag(graph), [graph]);
  const isDirty = workingRobotYaml !== savedRobotYaml;
  const canSave = validation.ok && dagValidation.ok && isDirty;

  function loadTemplate(template: StarterTemplate) {
    const next = createStarterProjectSnapshot(
      template,
      `hiyelx-${template}`,
      `HIYELX ${template}`,
    );
    setManifest(next.manifest);
    setSavedRobotYaml(next.robotYaml);
    setWorkingRobotYaml(next.robotYaml);
    setGraph(parseRobotGraphYaml(next.graphYaml));
    setLayout(next.layout);
    setSelectedNodeId(null);
    setActiveProfile(next.manifest.workspace.default_profile);
  }

  function applyConfigUpdate(nextConfig: RobotConfig) {
    const nextYaml = patchRobotConfigYamlRoundTrip(workingRobotYaml, nextConfig);
    setWorkingRobotYaml(nextYaml);
  }

  function handleAddComponent(spec: BuiltInModelSpec) {
    if (!validation.ok) return;
    const baseName = spec.model.replaceAll(".", "_");
    let suffix = 1;
    let candidateId = `${baseName}_${suffix}`;
    const existingIds = new Set([
      ...graph.nodes.map((n) => n.id),
      ...validation.config.components.map((c) => c.id),
    ]);
    while (existingIds.has(candidateId)) {
      suffix += 1;
      candidateId = `${baseName}_${suffix}`;
    }

    const nextGraph: RobotGraphDocument = {
      ...graph,
      nodes: [
        ...graph.nodes,
        {
          id: candidateId,
          kind: nodeKindForCategory(spec.category),
          label: `${spec.label} ${suffix}`,
          component_id: candidateId,
          category: spec.category,
          model: spec.model,
        },
      ],
    };
    setGraph(nextGraph);
    setLayout({
      ...layout,
      positions: {
        ...layout.positions,
        [candidateId]: { x: 120 + nextGraph.nodes.length * 40, y: 240 },
      },
    });
    setSelectedNodeId(candidateId);

    applyConfigUpdate({
      ...validation.config,
      components: [
        ...validation.config.components,
        {
          id: candidateId,
          category: spec.category,
          model: spec.model,
          depends_on: [],
          settings: { ...spec.defaultSettings },
        },
      ],
    });
  }

  function handleDeleteSelectedNode() {
    if (!selectedNodeId || !validation.ok) return;
    const targetNode = graph.nodes.find((n) => n.id === selectedNodeId);
    const nextGraph: RobotGraphDocument = {
      ...graph,
      nodes: graph.nodes.filter((n) => n.id !== selectedNodeId),
      edges: graph.edges.filter((e) => e.source !== selectedNodeId && e.target !== selectedNodeId),
    };
    setGraph(nextGraph);
    setSelectedNodeId(null);

    if (targetNode?.component_id) {
      const removedId = targetNode.component_id;
      applyConfigUpdate({
        ...validation.config,
        components: validation.config.components
          .filter((c) => c.id !== removedId)
          .map((c) => ({
            ...c,
            depends_on: c.depends_on.filter((dep) => dep !== removedId),
          })),
      });
    }
  }

  function handleConnectEdge(source: string, target: string, kind: StudioEdgeKind) {
    if (kind === "dependency" && source === target) return;
    const edgeId = `${kind}-${source}-${target}-${graph.edges.length + 1}`;
    const nextGraph: RobotGraphDocument = {
      ...graph,
      edges: [...graph.edges, { id: edgeId, source, target, kind }],
    };
    setGraph(nextGraph);

    if (kind === "dependency" && validation.ok) {
      const nextDag = validateDependencyDag(nextGraph);
      if (nextDag.ok) {
        const projected = projectDependsOn(nextGraph);
        applyConfigUpdate({
          ...validation.config,
          components: validation.config.components.map((comp) => ({
            ...comp,
            depends_on: projected[comp.id] ?? comp.depends_on,
          })),
        });
      }
    }
  }

  async function handleAutoLayout() {
    const nextPositions = await computeAutoLayout(graph);
    setLayout({ schema_version: "1", positions: nextPositions });
  }

  function handleUpdateRobotMetadata(patch: {
    name?: string;
    tick_rate_hz?: number;
    log_level?: string;
  }) {
    if (!validation.ok) return;
    applyConfigUpdate({
      ...validation.config,
      robot: {
        ...validation.config.robot,
        ...(patch.name !== undefined ? { name: patch.name } : {}),
      },
      runtime: {
        ...validation.config.runtime,
        ...(patch.tick_rate_hz !== undefined ? { tick_rate_hz: patch.tick_rate_hz } : {}),
        ...(patch.log_level !== undefined ? { log_level: patch.log_level } : {}),
      },
    });
  }

  function handleSave() {
    if (!canSave) return;
    setSavedRobotYaml(workingRobotYaml);
  }

  const commands: readonly PaletteCommand[] = [
    {
      id: "view-builder",
      label: "Switch to Robot Builder (M03)",
      group: "Navigation",
      onRun: () => setActiveView("builder"),
    },
    {
      id: "view-config",
      label: "Switch to Configuration Editor (M05)",
      group: "Navigation",
      onRun: () => setActiveView("config"),
    },
    {
      id: "view-diff",
      label: "Inspect Configuration Diff",
      group: "Navigation",
      onRun: () => setActiveView("diff"),
    },
    {
      id: "auto-layout",
      label: "Run ELK Auto-Layout on Robot Graph",
      group: "Robot Builder",
      onRun: () => {
        void handleAutoLayout();
      },
    },
    {
      id: "template-rover",
      label: "Load Template: canonical-mock-rover",
      group: "Project",
      onRun: () => loadTemplate("canonical-mock-rover"),
    },
    {
      id: "template-motor",
      label: "Load Template: single-sim-motor",
      group: "Project",
      onRun: () => loadTemplate("single-sim-motor"),
    },
  ];

  const navItems: readonly { id: StudioViewId; label: string; icon: typeof Network }[] = [
    { id: "builder", label: "Robot Builder", icon: Network },
    { id: "config", label: "Config & YAML", icon: Code2 },
    { id: "diff", label: "Diff", icon: GitCompare },
  ];

  return (
    <div className="flex h-screen flex-col bg-slate-950 text-slate-100">
      <header className="flex h-12 shrink-0 items-center justify-between border-b border-slate-800 bg-slate-900 px-4">
        <div className="flex items-center gap-4">
          <span className="font-mono text-sm font-bold tracking-wide text-cyan-400">
            HIYELX STUDIO <span className="font-normal text-slate-400">P4 · RDE</span>
          </span>
          <nav aria-label="Studio views" className="flex items-center gap-1">
            {navItems.map((item) => {
              const Icon = item.icon;
              const active = activeView === item.id;
              return (
                <button
                  key={item.id}
                  type="button"
                  aria-current={active ? "page" : undefined}
                  className={`inline-flex items-center gap-1.5 rounded-md px-2.5 py-1 text-xs font-medium ${
                    active
                      ? "bg-slate-800 text-cyan-300"
                      : "text-slate-400 hover:bg-slate-800/60 hover:text-slate-200"
                  }`}
                  onClick={() => setActiveView(item.id)}
                >
                  <Icon className="h-3.5 w-3.5" aria-hidden="true" />
                  {item.label}
                </button>
              );
            })}
          </nav>
        </div>

        <div className="flex items-center gap-2">
          <StatusBadge tone={validation.ok && dagValidation.ok ? "success" : "error"}>
            {validation.ok && dagValidation.ok ? "Config valid" : "Validation error"}
          </StatusBadge>

          <button
            type="button"
            className="inline-flex items-center gap-1 rounded-md border border-slate-700 bg-slate-950 px-2.5 py-1 text-xs text-slate-200 hover:bg-slate-800"
            onClick={() => setCommandPaletteOpen(true)}
          >
            <Command className="h-3.5 w-3.5" aria-hidden="true" />
            Commands
          </button>

          <button
            type="button"
            disabled={!canSave}
            className="inline-flex items-center gap-1 rounded-md bg-cyan-600 px-3 py-1 text-xs font-semibold text-slate-950 hover:bg-cyan-500 disabled:bg-slate-800 disabled:text-slate-500"
            onClick={handleSave}
          >
            <Save className="h-3.5 w-3.5" aria-hidden="true" />
            {isDirty ? "Save robot.yaml" : "Saved"}
          </button>
        </div>
      </header>

      <div className="flex min-h-0 flex-1">
        <ProjectSidebar
          manifest={manifest}
          activeProfile={activeProfile}
          onSelectProfile={setActiveProfile}
          onCreateFromTemplate={loadTemplate}
        />

        <main className="flex min-h-0 min-w-0 flex-1 flex-col">
          {activeView === "builder" && (
            <RobotBuilderCanvas
              graph={graph}
              layout={layout}
              selectedNodeId={selectedNodeId}
              activeEdgeKind={activeEdgeKind}
              onSelectNode={setSelectedNodeId}
              onChangeEdgeKind={setActiveEdgeKind}
              onAddComponent={handleAddComponent}
              onDeleteSelectedNode={handleDeleteSelectedNode}
              onConnectEdge={handleConnectEdge}
              onAutoLayout={() => {
                void handleAutoLayout();
              }}
            />
          )}

          {activeView === "config" && (
            <ConfigEditorView
              robotYaml={workingRobotYaml}
              parsedConfig={validation.ok ? validation.config : null}
              diagnostics={validation.diagnostics}
              onYamlChange={setWorkingRobotYaml}
              onUpdateRobotMetadata={handleUpdateRobotMetadata}
            />
          )}

          {activeView === "diff" && (
            <DiffPanel savedYaml={savedRobotYaml} workingYaml={workingRobotYaml} />
          )}
        </main>
      </div>

      <footer className="flex h-7 shrink-0 items-center justify-between border-t border-slate-800 bg-slate-900 px-4 font-mono text-[11px] text-slate-400">
        <span>
          Local-first · No direct hardware access · Profile: {activeProfile}
        </span>
        <span>
          Schema: project v{manifest.schema_version} · robot v{manifest.runtime.robot_schema_version}
        </span>
      </footer>

      <CommandPalette
        open={commandPaletteOpen}
        commands={commands}
        onClose={() => setCommandPaletteOpen(false)}
      />
    </div>
  );
}

export function StudioApp() {
  return (
    <QueryClientProvider client={queryClient}>
      <StudioWorkbench />
    </QueryClientProvider>
  );
}
