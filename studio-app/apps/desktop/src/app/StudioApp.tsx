import { useEffect, useMemo, useRef, useState } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  Activity,
  Code2,
  Command,
  GitCompare,
  Network,
  Package,
  PlaySquare,
  Save,
  Stethoscope,
  Terminal,
  Waves,
} from "lucide-react";
import {
  StudioApiClient,
  StudioApiError,
  parseStudioLaunchUrl,
} from "@hiyelx/api-client";
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
  serializeRobotGraphYaml,
  validateDependencyDag,
  type RobotGraphDocument,
  type StudioEdgeKind,
  type StudioNodeKind,
} from "@hiyelx/graph-engine";
import {
  BUILTIN_MANIFEST_CATALOG,
  type ComponentManifest,
} from "@hiyelx/manifest-engine";
import {
  createStarterProjectSnapshot,
  serializeProjectManifestYaml,
  type CanvasLayoutDocument,
  type ProjectManifest,
  type StarterTemplate,
} from "@hiyelx/project-engine";
import {
  SequenceGapDetector,
  TelemetryRingBuffer,
  classifyFault,
  type StructuredLogRecord,
  type TelemetryFrame,
} from "@hiyelx/telemetry";
import {
  createStarterWorkflow,
  serializeApplicationWorkflowYaml,
  type ApplicationWorkflowDocument,
} from "@hiyelx/workflow-engine";
import { StatusBadge } from "@hiyelx/ui";
import { ApplicationStudioView } from "../../../../features/applications/ApplicationStudioView.tsx";
import { ConfigEditorView } from "../../../../features/configuration/ConfigEditorView.tsx";
import { DiffPanel } from "../../../../features/configuration/DiffPanel.tsx";
import { DataFlowView } from "../../../../features/data-flow/DataFlowView.tsx";
import { DevEnvView } from "../../../../features/dev-env/DevEnvView.tsx";
import { DiagnosticsView } from "../../../../features/diagnostics/DiagnosticsView.tsx";
import { ComponentExplorerView } from "../../../../features/explorer/ComponentExplorerView.tsx";
import { MonitorView, type StreamConnectionStatus } from "../../../../features/monitor/MonitorView.tsx";
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
  const [workflow, setWorkflow] = useState<ApplicationWorkflowDocument>(() => {
    const parsed = validateRobotConfigYaml(initialBundle.robotYaml);
    return createStarterWorkflow(parsed.ok ? parsed.config : null);
  });

  // P7 bounded telemetry ring buffer + live 127.0.0.1 SSE connection state.
  const telemetryBufferRef = useRef(new TelemetryRingBuffer<TelemetryFrame>(120));
  const gapDetectorRef = useRef(new SequenceGapDetector());
  const apiClientRef = useRef<StudioApiClient | null>(null);
  const streamAbortRef = useRef<AbortController | null>(null);
  const seqRef = useRef(0);
  const [telemetryFrames, setTelemetryFrames] = useState<readonly TelemetryFrame[]>([]);
  const [diagnosticLogs, setDiagnosticLogs] = useState<readonly StructuredLogRecord[]>([]);
  const [streamStatus, setStreamStatus] = useState<StreamConnectionStatus>("disconnected");
  const [droppedFrames, setDroppedFrames] = useState(0);
  const [missingSequences, setMissingSequences] = useState(0);
  const [connectedOrigin, setConnectedOrigin] = useState<string | null>(null);
  const [liveSessions, setLiveSessions] = useState<readonly string[]>([]);
  const [selectedLiveSession, setSelectedLiveSession] = useState<string | null>(null);
  const [connectionError, setConnectionError] = useState<string | null>(null);

  useEffect(() => {
    return () => {
      streamAbortRef.current?.abort();
      apiClientRef.current = null;
    };
  }, []);

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
    const parsed = validateRobotConfigYaml(next.robotYaml);
    setWorkflow(createStarterWorkflow(parsed.ok ? parsed.config : null));
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

  function handleAddFromManifest(manifestItem: ComponentManifest) {
    handleAddComponent({
      model: manifestItem.model,
      label: manifestItem.name,
      category: manifestItem.category,
      defaultSettings: manifestItem.configuration.defaults,
      capabilities: manifestItem.capabilities,
    });
    setActiveView("builder");
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

  function handleInjectDiagnosticSample(withFault: boolean) {
    seqRef.current += 1;
    const seq = seqRef.current;
    const corrId = `${manifest.project.id}-seq-${seq}`;
    const timestampUtc = new Date().toISOString();
    const healthSummary = withFault ? "deadline exceeded during motor command" : null;
    const frame: TelemetryFrame = {
      schema_version: "1",
      session: manifest.project.id,
      sequence_number: seq,
      timestamp_monotonic_ms: seq * 500,
      timestamp_utc: timestampUtc,
      sampling_rate_hz: 2.0,
      buffer_limit: telemetryBufferRef.current.capacity,
      dropped_frames: telemetryBufferRef.current.droppedCount,
      correlation_id: corrId,
      runtime_state: "running",
      resources: [
        {
          identity: "drive_motor",
          kind: "motor",
          lifecycle_state: "running",
          health_status: withFault ? "degraded" : "healthy",
          health_summary: healthSummary,
          state: {
            angular_position_radians: Number((seq * 0.35).toFixed(3)),
            angular_velocity_radians_per_second: withFault ? 0.0 : 0.7,
            simulation_time_seconds: seq * 0.5,
            revision: seq,
          },
        },
      ],
    };
    telemetryBufferRef.current.push(frame);
    gapDetectorRef.current.observe(seq);
    setTelemetryFrames(telemetryBufferRef.current.toArray());
    setDroppedFrames(telemetryBufferRef.current.droppedCount);
    setMissingSequences(gapDetectorRef.current.missingCount);
    setStreamStatus(withFault ? "stale" : "live");

    const diagnosis = healthSummary ? classifyFault(healthSummary) : null;
    const logEntry: StructuredLogRecord = {
      schema_version: "1",
      sequence_number: seq,
      timestamp_utc: timestampUtc,
      level: withFault ? "ERROR" : "INFO",
      source: "drive_motor",
      correlation_id: corrId,
      fault_code: diagnosis?.faultCode ?? null,
      message: healthSummary ?? `Telemetry sample #${seq} validated cleanly.`,
    };
    setDiagnosticLogs((prev) => [logEntry, ...prev].slice(0, 200));
  }

  function startLiveSessionStream(client: StudioApiClient, sessionId: string) {
    streamAbortRef.current?.abort();
    const abortController = new AbortController();
    streamAbortRef.current = abortController;
    telemetryBufferRef.current.clear();
    gapDetectorRef.current.reset();
    setTelemetryFrames([]);
    setDroppedFrames(0);
    setMissingSequences(0);
    setSelectedLiveSession(sessionId);
    setConnectionError(null);

    void client.subscribeSessionStream(
      sessionId,
      {
        onStatus: (nextStatus) => setStreamStatus(nextStatus),
        onTelemetry: (frame) => {
          telemetryBufferRef.current.push(frame);
          gapDetectorRef.current.observe(frame.sequence_number);
          setTelemetryFrames(telemetryBufferRef.current.toArray());
          setDroppedFrames(telemetryBufferRef.current.droppedCount);
          setMissingSequences(gapDetectorRef.current.missingCount);
        },
        onDiagnostic: (record) => {
          setDiagnosticLogs((prev) => [record, ...prev].slice(0, 200));
        },
        onError: (err) => {
          setConnectionError(`${err.code}: ${err.message}`);
        },
      },
      { signal: abortController.signal },
    );
  }

  async function handleConnectLaunchUrl(rawLaunchUrl: string) {
    streamAbortRef.current?.abort();
    setConnectionError(null);
    let parsed: { readonly origin: string; readonly capability: string };
    try {
      parsed = parseStudioLaunchUrl(rawLaunchUrl);
    } catch (error) {
      setConnectionError(
        error instanceof StudioApiError
          ? `${error.code}: ${error.message}`
          : "Invalid Studio Host launch URL.",
      );
      return;
    }

    const client = new StudioApiClient({
      origin: parsed.origin,
      capability: parsed.capability,
    });
    apiClientRef.current = client;
    setConnectedOrigin(parsed.origin);
    setStreamStatus("connecting");

    try {
      await client.fetchMeta();
      const sessions = await client.fetchSessions();
      setLiveSessions(sessions);
      const firstSession = sessions[0];
      if (firstSession !== undefined) {
        startLiveSessionStream(client, firstSession);
      } else {
        setSelectedLiveSession(null);
        setStreamStatus("disconnected");
      }
    } catch (error) {
      setStreamStatus("disconnected");
      setConnectionError(
        error instanceof StudioApiError
          ? `${error.code}: ${error.message}`
          : "Could not reach local Studio Host.",
      );
    }
  }

  function handleSelectLiveSession(sessionId: string) {
    const client = apiClientRef.current;
    if (client === null || !sessionId) return;
    startLiveSessionStream(client, sessionId);
  }

  function handleDisconnectLiveHost() {
    streamAbortRef.current?.abort();
    streamAbortRef.current = null;
    apiClientRef.current = null;
    setConnectedOrigin(null);
    setLiveSessions([]);
    setSelectedLiveSession(null);
    setConnectionError(null);
    setStreamStatus("disconnected");
  }

  function handleAddFlowEdge(
    source: string,
    target: string,
    kind: "data" | "command" | "feedback",
    topic: string,
  ) {
    const edgeId = `${kind}-${source}-${target}-${graph.edges.length + 1}`;
    setGraph({
      ...graph,
      edges: [...graph.edges, { id: edgeId, source, target, kind, topic }],
    });
  }

  function handleRemoveFlowEdge(edgeId: string) {
    setGraph({
      ...graph,
      edges: graph.edges.filter((edge) => edge.id !== edgeId),
    });
  }

  function handleClearTelemetry() {
    telemetryBufferRef.current.clear();
    gapDetectorRef.current.reset();
    seqRef.current = 0;
    setTelemetryFrames([]);
    setDroppedFrames(0);
    setMissingSequences(0);
    setStreamStatus("disconnected");
  }

  const commands: readonly PaletteCommand[] = [
    {
      id: "view-builder",
      label: "Switch to Robot Builder (M03)",
      group: "Navigation",
      onRun: () => setActiveView("builder"),
    },
    {
      id: "view-data-flow",
      label: "Switch to Connection & Data Flow Designer (M06)",
      group: "Navigation",
      onRun: () => setActiveView("data-flow"),
    },
    {
      id: "view-explorer",
      label: "Switch to Component & Driver Explorer (M04)",
      group: "Navigation",
      onRun: () => setActiveView("explorer"),
    },
    {
      id: "view-applications",
      label: "Switch to Application Studio (M07)",
      group: "Development",
      onRun: () => setActiveView("applications"),
    },
    {
      id: "view-dev-env",
      label: "Switch to Developer Environment (M08)",
      group: "Development",
      onRun: () => setActiveView("dev-env"),
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
      id: "view-monitor",
      label: "Switch to Live Telemetry Monitor (M10)",
      group: "Runtime Operations",
      onRun: () => setActiveView("monitor"),
    },
    {
      id: "view-diagnostics",
      label: "Switch to Diagnostics & Fault Explorer (M11)",
      group: "Runtime Operations",
      onRun: () => setActiveView("diagnostics"),
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
    { id: "data-flow", label: "Data Flow", icon: Waves },
    { id: "explorer", label: "Components", icon: Package },
    { id: "config", label: "Config & YAML", icon: Code2 },
    { id: "diff", label: "Diff", icon: GitCompare },
    { id: "applications", label: "Applications", icon: PlaySquare },
    { id: "dev-env", label: "DevEnv", icon: Terminal },
    { id: "monitor", label: "Monitor", icon: Activity },
    { id: "diagnostics", label: "Diagnostics", icon: Stethoscope },
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

          {activeView === "data-flow" && (
            <DataFlowView
              graph={graph}
              liveSamplingHz={telemetryFrames[telemetryFrames.length - 1]?.sampling_rate_hz ?? null}
              latestSequence={telemetryFrames[telemetryFrames.length - 1]?.sequence_number ?? null}
              onAddFlowEdge={handleAddFlowEdge}
              onRemoveFlowEdge={handleRemoveFlowEdge}
            />
          )}

          {activeView === "explorer" && (
            <ComponentExplorerView
              catalog={BUILTIN_MANIFEST_CATALOG}
              runtimeVersion={manifest.runtime.min_version}
              canAddToRobot={validation.ok}
              onAddManifestComponent={handleAddFromManifest}
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

          {activeView === "applications" && (
            <ApplicationStudioView
              workflow={workflow}
              robotConfig={validation.ok ? validation.config : null}
              onChangeWorkflow={setWorkflow}
            />
          )}

          {activeView === "dev-env" && (
            <DevEnvView
              files={[
                {
                  path: "robot/robot.yaml",
                  content: workingRobotYaml,
                  readOnly: false,
                  onChange: setWorkingRobotYaml,
                },
                {
                  path: "applications/main.yaml",
                  content: serializeApplicationWorkflowYaml(workflow),
                  readOnly: true,
                },
                {
                  path: "hiyelx.project.yaml",
                  content: serializeProjectManifestYaml(manifest),
                  readOnly: true,
                },
                {
                  path: "robot/connections/graph.yaml",
                  content: serializeRobotGraphYaml(graph),
                  readOnly: true,
                },
              ]}
            />
          )}

          {activeView === "monitor" && (
            <MonitorView
              status={streamStatus}
              frames={telemetryFrames}
              bufferCapacity={telemetryBufferRef.current.capacity}
              droppedFrames={droppedFrames}
              missingSequenceCount={missingSequences}
              connectedOrigin={connectedOrigin}
              liveSessions={liveSessions}
              selectedLiveSession={selectedLiveSession}
              connectionError={connectionError}
              onConnectLaunchUrl={(url) => {
                void handleConnectLaunchUrl(url);
              }}
              onSelectLiveSession={handleSelectLiveSession}
              onDisconnect={handleDisconnectLiveHost}
              onInjectDiagnosticSample={handleInjectDiagnosticSample}
              onClearBuffer={handleClearTelemetry}
            />
          )}

          {activeView === "diagnostics" && <DiagnosticsView logs={diagnosticLogs} />}
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
