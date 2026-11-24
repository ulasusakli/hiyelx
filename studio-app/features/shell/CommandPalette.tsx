import { useState } from "react";
import { Terminal } from "lucide-react";

export interface PaletteCommand {
  readonly id: string;
  readonly label: string;
  readonly group: string;
  readonly onRun: () => void;
}

export function CommandPalette({
  open,
  commands,
  onClose,
}: {
  readonly open: boolean;
  readonly commands: readonly PaletteCommand[];
  readonly onClose: () => void;
}) {
  const [query, setQuery] = useState("");
  if (!open) return null;

  const trimmed = query.trim().toLowerCase();
  const filtered = commands.filter(
    (cmd) =>
      trimmed.length === 0 ||
      cmd.label.toLowerCase().includes(trimmed) ||
      cmd.group.toLowerCase().includes(trimmed),
  );

  return (
    <div
      role="dialog"
      aria-label="Command Palette"
      className="fixed inset-0 z-50 flex items-start justify-center bg-slate-950/70 pt-24 backdrop-blur-xs"
    >
      <div className="w-full max-w-lg rounded-xl border border-slate-700 bg-slate-900 shadow-2xl">
        <div className="flex items-center gap-2 border-b border-slate-800 px-3 py-2.5">
          <Terminal className="h-4 w-4 text-slate-400" aria-hidden="true" />
          <input
            aria-label="Filter commands"
            autoFocus
            className="w-full bg-transparent text-sm text-slate-100 placeholder:text-slate-500 focus:outline-none"
            placeholder="Type a command (Builder, YAML, Diff, Auto-Layout, Template)..."
            value={query}
            onChange={(event) => setQuery(event.target.value)}
          />
          <button
            type="button"
            className="rounded border border-slate-700 px-2 py-0.5 text-xs text-slate-300 hover:bg-slate-800"
            onClick={onClose}
          >
            Esc
          </button>
        </div>
        <ul className="max-h-72 overflow-y-auto p-2">
          {filtered.map((cmd) => (
            <li key={cmd.id}>
              <button
                type="button"
                className="flex w-full items-center justify-between rounded-lg px-3 py-2 text-left text-sm text-slate-200 hover:bg-slate-800"
                onClick={() => {
                  cmd.onRun();
                  setQuery("");
                  onClose();
                }}
              >
                <span>{cmd.label}</span>
                <span className="text-xs text-slate-400">{cmd.group}</span>
              </button>
            </li>
          ))}
          {filtered.length === 0 && (
            <li className="px-3 py-4 text-center text-xs text-slate-400">No matching commands.</li>
          )}
        </ul>
      </div>
    </div>
  );
}
