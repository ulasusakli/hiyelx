import { useMemo, useState } from "react";
import { CheckCircle2, Package, Plus, Search, ShieldAlert, TerminalSquare } from "lucide-react";
import {
  RUNTIME_COMPONENT_CATEGORIES,
  type RuntimeComponentCategory,
} from "@hiyelx/graph-engine";
import {
  COMPONENT_CAPABILITIES,
  evaluateManifestCompatibility,
  filterManifests,
  type ComponentCapability,
  type ComponentManifest,
} from "@hiyelx/manifest-engine";
import { StatusBadge } from "@hiyelx/ui";

export function ComponentExplorerView({
  catalog,
  runtimeVersion,
  canAddToRobot,
  onAddManifestComponent,
}: {
  readonly catalog: readonly ComponentManifest[];
  readonly runtimeVersion: string;
  readonly canAddToRobot: boolean;
  readonly onAddManifestComponent: (manifest: ComponentManifest) => void;
}) {
  const [query, setQuery] = useState("");
  const [category, setCategory] = useState<RuntimeComponentCategory | "all">("all");
  const [capability, setCapability] = useState<ComponentCapability | "all">("all");
  const [compatibleOnly, setCompatibleOnly] = useState(false);
  const [selectedId, setSelectedId] = useState<string | null>(catalog[0]?.id ?? null);

  const filtered = useMemo(
    () =>
      filterManifests(catalog, {
        query,
        category,
        capability,
        compatibleOnly,
        runtimeVersion,
      }),
    [catalog, query, category, capability, compatibleOnly, runtimeVersion],
  );

  const selected =
    filtered.find((item) => item.id === selectedId) ?? filtered[0] ?? null;

  const selectedReport = useMemo(
    () =>
      selected !== null
        ? evaluateManifestCompatibility(selected, runtimeVersion, catalog)
        : null,
    [selected, runtimeVersion, catalog],
  );

  return (
    <section
      aria-label="Component and Driver Explorer"
      className="grid min-h-0 flex-1 grid-cols-1 divide-y divide-slate-800 lg:grid-cols-12 lg:divide-x lg:divide-y-0"
    >
      <div className="flex min-h-0 flex-col bg-slate-950 lg:col-span-7">
        <div className="flex flex-wrap items-center gap-2 border-b border-slate-800 bg-slate-900/60 p-3">
          <div className="relative min-w-[200px] flex-1">
            <Search
              className="pointer-events-none absolute top-2 left-2.5 h-3.5 w-3.5 text-slate-500"
              aria-hidden="true"
            />
            <input
              aria-label="Search components and drivers"
              type="text"
              className="w-full rounded-md border border-slate-700 bg-slate-950 py-1.5 pr-3 pl-8 text-xs text-slate-100 placeholder:text-slate-500"
              placeholder="Search id, model, or driver name..."
              value={query}
              onChange={(event) => setQuery(event.target.value)}
            />
          </div>

          <select
            aria-label="Filter by category"
            className="rounded-md border border-slate-700 bg-slate-950 px-2.5 py-1.5 text-xs text-slate-100"
            value={category}
            onChange={(event) =>
              setCategory(event.target.value as RuntimeComponentCategory | "all")
            }
          >
            <option value="all">All categories</option>
            {RUNTIME_COMPONENT_CATEGORIES.map((cat) => (
              <option key={cat} value={cat}>
                {cat}
              </option>
            ))}
          </select>

          <select
            aria-label="Filter by capability"
            className="rounded-md border border-slate-700 bg-slate-950 px-2.5 py-1.5 font-mono text-xs text-slate-100"
            value={capability}
            onChange={(event) =>
              setCapability(event.target.value as ComponentCapability | "all")
            }
          >
            <option value="all">All capabilities</option>
            {COMPONENT_CAPABILITIES.map((cap) => (
              <option key={cap} value={cap}>
                {cap}
              </option>
            ))}
          </select>

          <label className="inline-flex items-center gap-1.5 text-xs text-slate-300">
            <input
              type="checkbox"
              checked={compatibleOnly}
              onChange={(event) => setCompatibleOnly(event.target.checked)}
            />
            Compatible only
          </label>
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto p-3">
          <p className="mb-2 text-xs text-slate-400">
            Showing {filtered.length} of {catalog.length} manifests (Runtime target v
            {runtimeVersion})
          </p>
          <div className="grid grid-cols-1 gap-2.5 md:grid-cols-2">
            {filtered.map((item) => {
              const report = evaluateManifestCompatibility(item, runtimeVersion, catalog);
              const isSelected = selected?.id === item.id;
              return (
                <button
                  key={item.id}
                  type="button"
                  className={`rounded-xl border p-3 text-left transition ${
                    isSelected
                      ? "border-cyan-400 bg-slate-900"
                      : "border-slate-800 bg-slate-900/50 hover:border-slate-700"
                  }`}
                  onClick={() => setSelectedId(item.id)}
                >
                  <div className="flex items-start justify-between gap-2">
                    <span className="inline-flex items-center gap-1.5 text-sm font-semibold text-slate-100">
                      <Package className="h-4 w-4 text-cyan-400" aria-hidden="true" />
                      {item.name}
                    </span>
                    <StatusBadge tone={report.compatible ? "success" : "error"}>
                      {report.compatible ? "Compatible" : "Incompatible"}
                    </StatusBadge>
                  </div>
                  <p className="mt-1 font-mono text-xs text-cyan-300">{item.model}</p>
                  <p className="mt-1 line-clamp-2 text-xs text-slate-400">
                    {item.description ?? item.id}
                  </p>
                  <div className="mt-2 flex flex-wrap gap-1">
                    <span className="rounded bg-slate-800 px-1.5 py-0.5 font-mono text-[10px] text-slate-300">
                      {item.type}
                    </span>
                    <span className="rounded bg-slate-800 px-1.5 py-0.5 font-mono text-[10px] text-slate-300">
                      {item.category}
                    </span>
                    <span className="rounded bg-slate-800 px-1.5 py-0.5 font-mono text-[10px] text-slate-400">
                      v{item.version}
                    </span>
                  </div>
                </button>
              );
            })}
          </div>
          {filtered.length === 0 && (
            <p className="py-10 text-center text-xs text-slate-400">
              No manifests match the active filters.
            </p>
          )}
        </div>
      </div>

      <div className="flex min-h-0 flex-col overflow-y-auto bg-slate-900/40 p-4 lg:col-span-5">
        {selected !== null && selectedReport !== null ? (
          <div className="space-y-4">
            <div className="flex items-start justify-between gap-3 border-b border-slate-800 pb-3">
              <div>
                <p className="text-[11px] font-bold tracking-wider text-cyan-400 uppercase">
                  Manifest Inspector · M04
                </p>
                <h2 className="mt-0.5 text-base font-semibold text-slate-100">
                  {selected.name}
                </h2>
                <p className="font-mono text-xs text-slate-400">
                  {selected.id} · manifest v{selected.manifest_version}
                </p>
              </div>
              <button
                type="button"
                disabled={!selectedReport.compatible || !canAddToRobot}
                className="inline-flex shrink-0 items-center gap-1 rounded-md bg-cyan-600 px-3 py-1.5 text-xs font-semibold text-slate-950 hover:bg-cyan-500 disabled:bg-slate-800 disabled:text-slate-500"
                onClick={() => onAddManifestComponent(selected)}
              >
                <Plus className="h-3.5 w-3.5" aria-hidden="true" />
                Add to Robot Builder
              </button>
            </div>

            <div className="rounded-lg border border-slate-800 bg-slate-950/70 p-3 text-xs">
              <div className="flex items-center justify-between">
                <span className="font-semibold text-slate-300">Compatibility Check</span>
                {selectedReport.compatible ? (
                  <StatusBadge tone="success">
                    <CheckCircle2 className="h-3 w-3" aria-hidden="true" />
                    Runtime &gt;= {selected.runtime.min_version}
                  </StatusBadge>
                ) : (
                  <StatusBadge tone="error">
                    <ShieldAlert className="h-3 w-3" aria-hidden="true" />
                    {selectedReport.status}
                  </StatusBadge>
                )}
              </div>
              {selectedReport.issues.length > 0 && (
                <ul className="mt-2 list-disc space-y-1 pl-4 text-rose-300">
                  {selectedReport.issues.map((issue, idx) => (
                    <li key={idx}>{issue.message}</li>
                  ))}
                </ul>
              )}
            </div>

            <div>
              <h3 className="mb-1.5 text-xs font-semibold text-slate-400">
                Declared Capabilities ({selected.capabilities.length})
              </h3>
              <div className="flex flex-wrap gap-1.5">
                {selected.capabilities.map((cap) => (
                  <span
                    key={cap}
                    className="rounded-md border border-slate-700 bg-slate-950 px-2 py-0.5 font-mono text-xs text-emerald-300"
                  >
                    {cap}
                  </span>
                ))}
              </div>
            </div>

            <div>
              <h3 className="mb-1.5 text-xs font-semibold text-slate-400">
                Interfaces ({selected.interfaces.length})
              </h3>
              <ul className="space-y-1 font-mono text-xs text-slate-300">
                {selected.interfaces.map((iface) => (
                  <li
                    key={iface.name}
                    className="flex items-center justify-between rounded border border-slate-800 bg-slate-950 px-2.5 py-1"
                  >
                    <span>{iface.name}</span>
                    <span className="text-slate-400">
                      {iface.direction} · {iface.type}
                    </span>
                  </li>
                ))}
              </ul>
            </div>

            <div>
              <h3 className="mb-1 text-xs font-semibold text-slate-400">Configuration Schema</h3>
              <p className="font-mono text-xs text-slate-300">{selected.configuration.schema}</p>
            </div>

            {selected.scaffold_command && (
              <div className="rounded-lg border border-slate-800 bg-slate-950 p-3">
                <p className="mb-1.5 flex items-center gap-1.5 text-xs font-semibold text-cyan-400">
                  <TerminalSquare className="h-3.5 w-3.5" aria-hidden="true" />
                  External Driver SDK Scaffold (CLI)
                </p>
                <code className="block overflow-x-auto font-mono text-[11px] text-slate-200">
                  {selected.scaffold_command}
                </code>
              </div>
            )}
          </div>
        ) : (
          <p className="text-xs text-slate-400">Select a manifest to inspect its contract.</p>
        )}
      </div>
    </section>
  );
}
