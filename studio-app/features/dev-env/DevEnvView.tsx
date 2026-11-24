import { useState } from "react";
import { FileCode2, Lock, ShieldAlert, Terminal } from "lucide-react";
import { YamlCodeEditor } from "@hiyelx/code-editor";
import { StatusBadge } from "@hiyelx/ui";

export interface WorkspaceCodeFile {
  readonly path: string;
  readonly content: string;
  readonly readOnly: boolean;
  readonly onChange?: (next: string) => void;
}

const SANCTIONED_CLI_COMMANDS = [
  {
    id: "validate",
    label: "Validate Robot Config",
    command: "uv run hiyelx validate-config robot/robot.yaml",
    output: "configuration=valid (preview — run in your local shell or approved Tauri session)",
  },
  {
    id: "demo",
    label: "Run Deterministic Sim Demo",
    command: "uv run hiyelx demo sim-motor",
    output: "canonical deterministic loopback sim-motor demo ready",
  },
  {
    id: "runtime-status",
    label: "Check Local Runtime Sessions",
    command: "uv run hiyelx runtime runs list --json",
    output: "reads local SQLite run history without mutating active Runtime sessions",
  },
] as const;

export function DevEnvView({
  files,
}: {
  readonly files: readonly WorkspaceCodeFile[];
}) {
  const [selectedPath, setSelectedPath] = useState<string>(files[0]?.path ?? "");
  const [terminalApproved, setTerminalApproved] = useState(false);
  const [transcript, setTranscript] = useState<readonly string[]>([]);

  const activeFile = files.find((f) => f.path === selectedPath) ?? files[0] ?? null;

  function runSanctionedPreview(command: string, output: string) {
    if (!terminalApproved) return;
    setTranscript((prev) => [...prev, `$ ${command}`, `  ${output}`]);
  }

  return (
    <section
      aria-label="Developer Environment"
      className="flex min-h-0 flex-1 flex-col bg-slate-950"
    >
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-slate-800 bg-slate-900/60 px-4 py-2">
        <div className="flex flex-wrap items-center gap-1.5">
          {files.map((file) => {
            const active = activeFile?.path === file.path;
            return (
              <button
                key={file.path}
                type="button"
                className={`inline-flex items-center gap-1.5 rounded-md px-2.5 py-1 font-mono text-xs ${
                  active
                    ? "bg-slate-800 text-cyan-300"
                    : "text-slate-400 hover:bg-slate-800/60 hover:text-slate-200"
                }`}
                onClick={() => setSelectedPath(file.path)}
              >
                <FileCode2 className="h-3.5 w-3.5" aria-hidden="true" />
                {file.path}
              </button>
            );
          })}
        </div>

        <StatusBadge tone="neutral">
          <Lock className="h-3 w-3" aria-hidden="true" />
          Workspace-confined · Extensions terminal DENIED
        </StatusBadge>
      </div>

      <div className="min-h-[220px] flex-1 border-b border-slate-800">
        {activeFile !== null && (
          <YamlCodeEditor
            value={activeFile.content}
            readOnly={activeFile.readOnly}
            onChange={(next) => {
              if (!activeFile.readOnly && activeFile.onChange) {
                activeFile.onChange(next);
              }
            }}
          />
        )}
      </div>

      <div className="flex h-56 shrink-0 flex-col bg-slate-900/60 p-3 text-xs">
        <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
          <span className="inline-flex items-center gap-1.5 font-semibold text-slate-200">
            <Terminal className="h-3.5 w-3.5 text-cyan-400" aria-hidden="true" />
            Policy-Gated Developer Terminal (M08)
          </span>

          <div className="flex items-center gap-2">
            {terminalApproved ? (
              <>
                <StatusBadge tone="success">User-approved session active</StatusBadge>
                <button
                  type="button"
                  className="rounded border border-slate-700 px-2 py-0.5 text-slate-300 hover:bg-slate-800"
                  onClick={() => {
                    setTerminalApproved(false);
                    setTranscript([]);
                  }}
                >
                  Close Session
                </button>
              </>
            ) : (
              <StatusBadge tone="warning">
                <ShieldAlert className="h-3 w-3" aria-hidden="true" />
                Terminal locked (opt-in required)
              </StatusBadge>
            )}
          </div>
        </div>

        {!terminalApproved ? (
          <div className="flex flex-1 flex-col items-start justify-center gap-2 rounded-lg border border-slate-800 bg-slate-950 p-3">
            <p className="text-slate-300">
              ADR 0002 v1.1 Terminal Security Policy: Terminal sessions never start automatically,
              run isolated from Runtime Host permissions, and are denied to extensions by default.
            </p>
            <button
              type="button"
              className="rounded-md bg-cyan-600 px-3 py-1.5 font-semibold text-slate-950 hover:bg-cyan-500"
              onClick={() => setTerminalApproved(true)}
            >
              Start User-Approved Terminal Session
            </button>
          </div>
        ) : (
          <div className="flex min-h-0 flex-1 flex-col gap-2">
            <div className="flex flex-wrap gap-1.5">
              {SANCTIONED_CLI_COMMANDS.map((item) => (
                <button
                  key={item.id}
                  type="button"
                  className="rounded border border-slate-700 bg-slate-950 px-2 py-1 font-mono text-[11px] text-cyan-300 hover:bg-slate-800"
                  onClick={() => runSanctionedPreview(item.command, item.output)}
                >
                  {item.label}
                </button>
              ))}
            </div>
            <pre
              aria-label="Developer terminal output"
              className="min-h-0 flex-1 overflow-auto rounded-lg border border-slate-800 bg-slate-950 p-2.5 font-mono text-[11px] text-slate-200"
            >
              {transcript.length > 0
                ? transcript.join("\n")
                : "# User-approved workspace terminal ready (isolated from Runtime Host; extensions denied)."}
            </pre>
          </div>
        )}
      </div>
    </section>
  );
}
