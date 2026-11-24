import { useMemo, useState } from "react";
import { AlertOctagon, Filter, Search } from "lucide-react";
import {
  classifyFault,
  type StructuredLogRecord,
} from "@hiyelx/telemetry";
import { StatusBadge } from "@hiyelx/ui";

export function DiagnosticsView({
  logs,
}: {
  readonly logs: readonly StructuredLogRecord[];
}) {
  const [levelFilter, setLevelFilter] = useState<"ALL" | StructuredLogRecord["level"]>("ALL");
  const [correlationFilter, setCorrelationFilter] = useState("");
  const [query, setQuery] = useState("");

  const filteredLogs = useMemo(() => {
    const q = query.trim().toLowerCase();
    const corr = correlationFilter.trim().toLowerCase();
    return logs.filter((entry) => {
      if (levelFilter !== "ALL" && entry.level !== levelFilter) return false;
      if (corr.length > 0 && !entry.correlation_id.toLowerCase().includes(corr)) return false;
      if (q.length > 0) {
        const hay =
          `${entry.source} ${entry.message} ${entry.fault_code ?? ""} ${entry.correlation_id}`.toLowerCase();
        if (!hay.includes(q)) return false;
      }
      return true;
    });
  }, [logs, levelFilter, correlationFilter, query]);

  const activeFaults = useMemo(() => {
    const seen = new Set<string>();
    const list: { record: StructuredLogRecord; diagnosis: ReturnType<typeof classifyFault> }[] = [];
    for (const entry of logs) {
      if (!entry.fault_code && entry.level !== "ERROR" && entry.level !== "WARNING") continue;
      const diagnosis = classifyFault(entry.fault_code ?? entry.message);
      const key = `${diagnosis.faultCode}:${entry.correlation_id}`;
      if (seen.has(key)) continue;
      seen.add(key);
      list.push({ record: entry, diagnosis });
    }
    return list;
  }, [logs]);

  return (
    <section
      aria-label="Diagnostics and Debugging"
      className="grid min-h-0 flex-1 grid-cols-1 divide-y divide-slate-800 lg:grid-cols-12 lg:divide-x lg:divide-y-0"
    >
      <div className="flex min-h-0 flex-col bg-slate-950 lg:col-span-7">
        <div className="flex flex-wrap items-center gap-2 border-b border-slate-800 bg-slate-900/60 p-3">
          <div className="relative min-w-[180px] flex-1">
            <Search
              className="pointer-events-none absolute top-2 left-2.5 h-3.5 w-3.5 text-slate-500"
              aria-hidden="true"
            />
            <input
              aria-label="Search structured logs"
              type="text"
              className="w-full rounded-md border border-slate-700 bg-slate-950 py-1.5 pr-3 pl-8 text-xs text-slate-100 placeholder:text-slate-500"
              placeholder="Search message, source, fault code..."
              value={query}
              onChange={(event) => setQuery(event.target.value)}
            />
          </div>

          <input
            aria-label="Filter by correlation ID"
            type="text"
            className="w-40 rounded-md border border-slate-700 bg-slate-950 px-2.5 py-1.5 font-mono text-xs text-slate-100 placeholder:text-slate-500"
            placeholder="Correlation-ID"
            value={correlationFilter}
            onChange={(event) => setCorrelationFilter(event.target.value)}
          />

          <div className="inline-flex items-center gap-1">
            <Filter className="h-3.5 w-3.5 text-slate-400" aria-hidden="true" />
            <select
              aria-label="Filter by log level"
              className="rounded-md border border-slate-700 bg-slate-950 px-2 py-1.5 font-mono text-xs text-slate-100"
              value={levelFilter}
              onChange={(event) =>
                setLevelFilter(event.target.value as "ALL" | StructuredLogRecord["level"])
              }
            >
              {["ALL", "ERROR", "WARNING", "INFO", "DEBUG"].map((lvl) => (
                <option key={lvl} value={lvl}>
                  {lvl}
                </option>
              ))}
            </select>
          </div>
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto p-3 font-mono text-xs">
          {filteredLogs.length === 0 ? (
            <p className="py-10 text-center text-slate-400">
              No structured logs match the active filters.
            </p>
          ) : (
            <ul className="space-y-1.5">
              {filteredLogs.map((entry) => (
                <li
                  key={`${entry.sequence_number}-${entry.correlation_id}-${entry.source}`}
                  className="rounded-lg border border-slate-800 bg-slate-900/50 p-2.5"
                >
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <span className="font-semibold text-slate-100">
                      [{entry.level}] {entry.source}
                    </span>
                    <button
                      type="button"
                      className="rounded bg-slate-800 px-1.5 py-0.5 text-[11px] text-cyan-300 hover:bg-slate-700"
                      onClick={() => setCorrelationFilter(entry.correlation_id)}
                    >
                      corr: {entry.correlation_id}
                    </button>
                  </div>
                  <p className="mt-1 text-slate-300">{entry.message}</p>
                  <p className="mt-1 text-[10px] text-slate-500">
                    seq #{entry.sequence_number} · {entry.timestamp_utc}
                    {entry.fault_code ? ` · fault: ${entry.fault_code}` : ""}
                  </p>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>

      <div className="flex min-h-0 flex-col overflow-y-auto bg-slate-900/40 p-4 lg:col-span-5">
        <div className="mb-3 border-b border-slate-800 pb-2">
          <p className="text-[11px] font-bold tracking-wider text-cyan-400 uppercase">
            Fault Explorer · M11
          </p>
          <h2 className="mt-0.5 text-sm font-semibold text-slate-100">
            Root-Cause Analysis Cards ({activeFaults.length})
          </h2>
        </div>

        {activeFaults.length === 0 ? (
          <p className="text-xs text-slate-400">
            No active faults detected. Trigger a diagnostic fault sample in Monitor or connect a
            degraded Runtime session to inspect root-cause guidance.
          </p>
        ) : (
          <div className="space-y-3">
            {activeFaults.map(({ record, diagnosis }) => (
              <article
                key={`${diagnosis.faultCode}-${record.correlation_id}`}
                className="rounded-xl border border-rose-900/60 bg-slate-950 p-3 text-xs"
              >
                <div className="flex items-start justify-between gap-2">
                  <span className="inline-flex items-center gap-1.5 font-semibold text-rose-200">
                    <AlertOctagon className="h-4 w-4 text-rose-400" aria-hidden="true" />
                    {diagnosis.title}
                  </span>
                  <StatusBadge tone={diagnosis.severity === "error" ? "error" : "warning"}>
                    {diagnosis.faultCode}
                  </StatusBadge>
                </div>
                <p className="mt-1 font-mono text-[11px] text-slate-400">
                  source: {record.source} · correlation: {record.correlation_id}
                </p>

                <div className="mt-2.5">
                  <p className="font-semibold text-slate-300">Likely causes</p>
                  <ul className="mt-1 list-disc space-y-0.5 pl-4 text-slate-400">
                    {diagnosis.likelyCauses.map((cause, idx) => (
                      <li key={idx}>{cause}</li>
                    ))}
                  </ul>
                </div>

                <div className="mt-2.5">
                  <p className="font-semibold text-slate-300">Recommended checks</p>
                  <ul className="mt-1 list-disc space-y-0.5 pl-4 text-emerald-300/90">
                    {diagnosis.recommendedChecks.map((check, idx) => (
                      <li key={idx}>{check}</li>
                    ))}
                  </ul>
                </div>
              </article>
            ))}
          </div>
        )}
      </div>
    </section>
  );
}
