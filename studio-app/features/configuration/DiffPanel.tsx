import { useMemo } from "react";
import { computeLineDiff } from "@hiyelx/config-engine";

export function DiffPanel({
  savedYaml,
  workingYaml,
}: {
  readonly savedYaml: string;
  readonly workingYaml: string;
}) {
  const lines = useMemo(() => computeLineDiff(savedYaml, workingYaml), [savedYaml, workingYaml]);
  const changedCount = lines.filter((line) => line.kind !== "context").length;

  return (
    <section aria-label="Configuration Diff" className="flex min-h-0 flex-1 flex-col bg-slate-950">
      <div className="flex items-center justify-between border-b border-slate-800 bg-slate-900/60 px-4 py-2 text-xs">
        <span className="font-mono text-slate-200">Diff · Saved disk state ↔ Working robot.yaml</span>
        <span className="text-slate-400">
          {changedCount === 0 ? "No unsaved changes" : `${changedCount} changed lines`}
        </span>
      </div>
      <div className="min-h-0 flex-1 overflow-auto p-3 font-mono text-xs">
        {lines.map((line, index) => {
          const rowClass =
            line.kind === "add"
              ? "bg-emerald-950/60 text-emerald-300"
              : line.kind === "remove"
                ? "bg-rose-950/60 text-rose-300"
                : "text-slate-400";
          const prefix = line.kind === "add" ? "+" : line.kind === "remove" ? "-" : " ";
          return (
            <div key={index} className={`flex gap-3 px-2 py-0.5 ${rowClass}`}>
              <span className="w-8 shrink-0 text-right opacity-60">{line.oldLine ?? ""}</span>
              <span className="w-8 shrink-0 text-right opacity-60">{line.newLine ?? ""}</span>
              <span className="w-3 shrink-0 select-none">{prefix}</span>
              <span className="whitespace-pre">{line.text}</span>
            </div>
          );
        })}
      </div>
    </section>
  );
}
