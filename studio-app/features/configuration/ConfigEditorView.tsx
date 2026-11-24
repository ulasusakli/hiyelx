import { AlertTriangle, CheckCircle2 } from "lucide-react";
import { YamlCodeEditor } from "@hiyelx/code-editor";
import type {
  ConfigValidationDiagnostic,
  RobotConfig,
} from "@hiyelx/config-engine";
import { StatusBadge } from "@hiyelx/ui";

export function ConfigEditorView({
  robotYaml,
  parsedConfig,
  diagnostics,
  onYamlChange,
  onUpdateRobotMetadata,
}: {
  readonly robotYaml: string;
  readonly parsedConfig: RobotConfig | null;
  readonly diagnostics: readonly ConfigValidationDiagnostic[];
  readonly onYamlChange: (nextYaml: string) => void;
  readonly onUpdateRobotMetadata: (patch: {
    name?: string;
    tick_rate_hz?: number;
    log_level?: string;
  }) => void;
}) {
  return (
    <section
      aria-label="Configuration Editor"
      className="grid min-h-0 flex-1 grid-cols-1 divide-y divide-slate-800 lg:grid-cols-12 lg:divide-x lg:divide-y-0"
    >
      <div className="flex flex-col gap-4 overflow-y-auto bg-slate-900/40 p-4 lg:col-span-5">
        <div className="flex items-center justify-between">
          <div>
            <p className="text-[11px] font-bold tracking-wider text-cyan-400 uppercase">
              Inspector Form · M05
            </p>
            <h2 className="text-sm font-semibold text-slate-100">RobotConfig v2</h2>
          </div>
          {parsedConfig !== null ? (
            <StatusBadge tone="success">
              <CheckCircle2 className="h-3.5 w-3.5" aria-hidden="true" />
              Schema valid
            </StatusBadge>
          ) : (
            <StatusBadge tone="error">
              <AlertTriangle className="h-3.5 w-3.5" aria-hidden="true" />
              Invalid YAML ({diagnostics.length})
            </StatusBadge>
          )}
        </div>

        {parsedConfig !== null ? (
          <div className="space-y-3">
            <div>
              <label htmlFor="robot-name-input" className="mb-1 block text-xs text-slate-400">
                Robot name
              </label>
              <input
                id="robot-name-input"
                type="text"
                className="w-full rounded-md border border-slate-700 bg-slate-950 px-2.5 py-1.5 text-sm text-slate-100"
                value={parsedConfig.robot.name}
                onChange={(event) => onUpdateRobotMetadata({ name: event.target.value })}
              />
            </div>

            <div className="grid grid-cols-2 gap-3">
              <div>
                <label htmlFor="tick-rate-input" className="mb-1 block text-xs text-slate-400">
                  Tick rate (Hz)
                </label>
                <input
                  id="tick-rate-input"
                  type="number"
                  min={1}
                  step={1}
                  className="w-full rounded-md border border-slate-700 bg-slate-950 px-2.5 py-1.5 font-mono text-sm text-slate-100"
                  value={parsedConfig.runtime.tick_rate_hz}
                  onChange={(event) => {
                    const num = Number(event.target.value);
                    if (Number.isFinite(num) && num > 0) {
                      onUpdateRobotMetadata({ tick_rate_hz: num });
                    }
                  }}
                />
              </div>

              <div>
                <label htmlFor="log-level-select" className="mb-1 block text-xs text-slate-400">
                  Log level
                </label>
                <select
                  id="log-level-select"
                  className="w-full rounded-md border border-slate-700 bg-slate-950 px-2.5 py-1.5 font-mono text-sm text-slate-100"
                  value={parsedConfig.runtime.log_level}
                  onChange={(event) => onUpdateRobotMetadata({ log_level: event.target.value })}
                >
                  {["DEBUG", "INFO", "WARNING", "ERROR"].map((level) => (
                    <option key={level} value={level}>
                      {level}
                    </option>
                  ))}
                </select>
              </div>
            </div>

            <div className="border-t border-slate-800 pt-3">
              <p className="mb-2 text-xs font-semibold text-slate-400">
                Configured components ({parsedConfig.components.length})
              </p>
              <ul className="space-y-2">
                {parsedConfig.components.map((comp) => (
                  <li
                    key={comp.id}
                    className="rounded-lg border border-slate-800 bg-slate-950/70 p-2.5 text-xs"
                  >
                    <div className="flex items-center justify-between">
                      <span className="font-mono font-semibold text-slate-100">{comp.id}</span>
                      <span className="rounded bg-slate-800 px-1.5 py-0.5 font-mono text-[11px] text-cyan-300">
                        {comp.category}
                      </span>
                    </div>
                    <p className="mt-1 font-mono text-slate-400">model: {comp.model}</p>
                    {comp.depends_on.length > 0 && (
                      <p className="mt-0.5 font-mono text-slate-400">
                        depends_on: {comp.depends_on.join(", ")}
                      </p>
                    )}
                  </li>
                ))}
              </ul>
            </div>
          </div>
        ) : (
          <div
            role="alert"
            className="rounded-lg border border-rose-800/80 bg-rose-950/40 p-3 text-xs text-rose-200"
          >
            <p className="font-semibold">
              Visual form write-back is paused while robot.yaml has validation errors.
            </p>
            <p className="mt-1 text-rose-300">
              Fix the errors in the YAML editor on the right; your text will never be overwritten.
            </p>
            <ul className="mt-2 list-disc space-y-1 pl-4 font-mono">
              {diagnostics.map((diag, index) => (
                <li key={`${diag.path}-${index}`}>
                  {diag.path}
                  {diag.line !== null ? ` (line ${diag.line})` : ""}: {diag.message}
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>

      <div className="flex min-h-[360px] flex-col lg:col-span-7">
        <div className="flex items-center justify-between border-b border-slate-800 bg-slate-900/60 px-3 py-2 text-xs">
          <span className="font-mono text-slate-300">robot/robot.yaml (Monaco · Round-Trip)</span>
          <span className="text-slate-400">Fail-closed Pydantic/Zod v2 parity</span>
        </div>
        <div className="min-h-0 flex-1">
          <YamlCodeEditor value={robotYaml} onChange={onYamlChange} />
        </div>
      </div>
    </section>
  );
}
