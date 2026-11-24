import { useState } from "react";
import { Activity, AlertTriangle, Link2, PlugZap, Radio } from "lucide-react";
import type { TelemetryFrame } from "@hiyelx/telemetry";
import { StatusBadge } from "@hiyelx/ui";

export type StreamConnectionStatus =
  | "disconnected"
  | "connecting"
  | "live"
  | "stale"
  | "reconnecting";

function buildPolylinePoints(values: readonly number[], width: number, height: number): string {
  if (values.length === 0) return "";
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min || 1;
  return values
    .map((val, idx) => {
      const x = values.length === 1 ? width / 2 : (idx / (values.length - 1)) * width;
      const y = height - ((val - min) / span) * (height - 16) - 8;
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(" ");
}

export function MonitorView({
  status,
  frames,
  bufferCapacity,
  droppedFrames,
  missingSequenceCount,
  connectedOrigin,
  liveSessions,
  selectedLiveSession,
  connectionError,
  onConnectLaunchUrl,
  onSelectLiveSession,
  onDisconnect,
  onInjectDiagnosticSample,
  onClearBuffer,
}: {
  readonly status: StreamConnectionStatus;
  readonly frames: readonly TelemetryFrame[];
  readonly bufferCapacity: number;
  readonly droppedFrames: number;
  readonly missingSequenceCount: number;
  readonly connectedOrigin: string | null;
  readonly liveSessions: readonly string[];
  readonly selectedLiveSession: string | null;
  readonly connectionError: string | null;
  readonly onConnectLaunchUrl: (launchUrl: string) => void;
  readonly onSelectLiveSession: (session: string) => void;
  readonly onDisconnect: () => void;
  readonly onInjectDiagnosticSample: (withFault: boolean) => void;
  readonly onClearBuffer: () => void;
}) {
  const [launchUrlInput, setLaunchUrlInput] = useState("");
  const latest = frames[frames.length - 1] ?? null;
  const positions = frames.map(
    (frame) => frame.resources[0]?.state.angular_position_radians ?? 0,
  );
  const velocities = frames.map(
    (frame) => frame.resources[0]?.state.angular_velocity_radians_per_second ?? 0,
  );

  const badgeTone =
    status === "live"
      ? "success"
      : status === "stale" || status === "reconnecting"
        ? "warning"
        : "neutral";

  return (
    <section
      aria-label="Live Telemetry Monitor"
      className="flex min-h-0 flex-1 flex-col overflow-y-auto bg-slate-950 p-4"
    >
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3 border-b border-slate-800 pb-3">
        <div>
          <p className="text-[11px] font-bold tracking-wider text-cyan-400 uppercase">
            Live Telemetry Monitor · M10 (P7 SSE)
          </p>
          <h2 className="mt-0.5 text-base font-semibold text-slate-100">
            Bounded Time-Series &amp; Runtime Health
          </h2>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <StatusBadge tone={badgeTone}>
            <Radio className="h-3 w-3" aria-hidden="true" />
            {status === "live"
              ? "SSE Connected"
              : status === "disconnected"
                ? "Awaiting 127.0.0.1 SSE"
                : status}
          </StatusBadge>

          <button
            type="button"
            className="rounded-md border border-slate-700 bg-slate-900 px-2.5 py-1 text-xs text-slate-200 hover:bg-slate-800"
            onClick={() => onInjectDiagnosticSample(false)}
          >
            Sample Frame (Test)
          </button>

          <button
            type="button"
            className="rounded-md border border-amber-800/70 bg-amber-950/50 px-2.5 py-1 text-xs text-amber-200 hover:bg-amber-900/50"
            onClick={() => onInjectDiagnosticSample(true)}
          >
            Simulate Deadline Fault
          </button>

          <button
            type="button"
            className="rounded-md border border-slate-700 bg-slate-950 px-2.5 py-1 text-xs text-slate-400 hover:text-slate-200"
            onClick={onClearBuffer}
          >
            Clear Buffer
          </button>
        </div>
      </div>

      <div className="mb-4 rounded-xl border border-slate-800 bg-slate-900/50 p-3 text-xs">
        <div className="flex flex-wrap items-center gap-2">
          <Link2 className="h-3.5 w-3.5 text-cyan-400" aria-hidden="true" />
          <input
            aria-label="Local Studio Host launch URL"
            type="password"
            className="min-w-[260px] flex-1 rounded-md border border-slate-700 bg-slate-950 px-2.5 py-1.5 font-mono text-xs text-slate-100 placeholder:text-slate-500"
            placeholder="http://127.0.0.1:<port>/live#capability=<token> (in-memory only)"
            value={launchUrlInput}
            onChange={(event) => setLaunchUrlInput(event.target.value)}
          />
          <button
            type="button"
            className="inline-flex items-center gap-1 rounded-md bg-cyan-600 px-3 py-1.5 font-semibold text-slate-950 hover:bg-cyan-500 disabled:bg-slate-800 disabled:text-slate-500"
            disabled={launchUrlInput.trim().length === 0}
            onClick={() => {
              const raw = launchUrlInput.trim();
              setLaunchUrlInput("");
              onConnectLaunchUrl(raw);
            }}
          >
            <PlugZap className="h-3.5 w-3.5" aria-hidden="true" />
            Connect 127.0.0.1
          </button>
          {connectedOrigin !== null && (
            <button
              type="button"
              className="rounded-md border border-rose-800/70 bg-rose-950/50 px-2.5 py-1.5 text-rose-200 hover:bg-rose-900/50"
              onClick={onDisconnect}
            >
              Disconnect
            </button>
          )}
        </div>

        {connectedOrigin !== null && (
          <div className="mt-2 flex flex-wrap items-center gap-3 text-slate-300">
            <span className="font-mono text-[11px] text-emerald-300">Host: {connectedOrigin}</span>
            {liveSessions.length > 0 ? (
              <label className="inline-flex items-center gap-1.5">
                <span className="text-slate-400">Session:</span>
                <select
                  aria-label="Live Runtime session"
                  className="rounded border border-slate-700 bg-slate-950 px-2 py-1 font-mono text-xs text-slate-100"
                  value={selectedLiveSession ?? ""}
                  onChange={(event) => onSelectLiveSession(event.target.value)}
                >
                  {liveSessions.map((sessionId) => (
                    <option key={sessionId} value={sessionId}>
                      {sessionId}
                    </option>
                  ))}
                </select>
              </label>
            ) : (
              <span className="text-slate-400">No active local sessions reported by Host.</span>
            )}
          </div>
        )}

        {connectionError !== null && (
          <p role="alert" className="mt-2 font-mono text-rose-300">
            {connectionError}
          </p>
        )}
      </div>

      <div className="mb-4 grid grid-cols-2 gap-3 lg:grid-cols-4">
        <div className="rounded-lg border border-slate-800 bg-slate-900/50 p-3">
          <p className="text-[11px] text-slate-400">Buffer Occupancy</p>
          <p className="mt-1 font-mono text-lg font-bold text-slate-100">
            {frames.length} / {bufferCapacity}
          </p>
          <p className="text-[11px] text-slate-500">Drop-oldest backpressure</p>
        </div>

        <div className="rounded-lg border border-slate-800 bg-slate-900/50 p-3">
          <p className="text-[11px] text-slate-400">Dropped Frames</p>
          <p className="mt-1 font-mono text-lg font-bold text-slate-100">{droppedFrames}</p>
          <p className="text-[11px] text-slate-500">Bounded ring buffer evictions</p>
        </div>

        <div className="rounded-lg border border-slate-800 bg-slate-900/50 p-3">
          <p className="text-[11px] text-slate-400">Missing Sequences</p>
          <p
            className={`mt-1 font-mono text-lg font-bold ${
              missingSequenceCount > 0 ? "text-amber-300" : "text-emerald-300"
            }`}
          >
            {missingSequenceCount}
          </p>
          <p className="text-[11px] text-slate-500">Never silently interpolated</p>
        </div>

        <div className="rounded-lg border border-slate-800 bg-slate-900/50 p-3">
          <p className="text-[11px] text-slate-400">Sampling Rate</p>
          <p className="mt-1 font-mono text-lg font-bold text-slate-100">
            {latest ? `${latest.sampling_rate_hz.toFixed(1)} Hz` : "—"}
          </p>
          <p className="font-mono text-[11px] text-slate-500">
            {latest ? `seq #${latest.sequence_number}` : "No stream sample"}
          </p>
        </div>
      </div>

      <div className="mb-4 grid grid-cols-1 gap-4 lg:grid-cols-2">
        <div className="rounded-xl border border-slate-800 bg-slate-900/40 p-3">
          <div className="mb-2 flex items-center justify-between text-xs">
            <span className="inline-flex items-center gap-1.5 font-semibold text-cyan-300">
              <Activity className="h-3.5 w-3.5" aria-hidden="true" />
              Angular Position (rad)
            </span>
            <span className="font-mono text-slate-300">
              {latest
                ? `${(latest.resources[0]?.state.angular_position_radians ?? 0).toFixed(3)} rad`
                : "—"}
            </span>
          </div>
          <svg
            aria-label="Angular position chart"
            viewBox="0 0 400 120"
            className="h-32 w-full rounded bg-slate-950"
          >
            {positions.length > 0 && (
              <polyline
                fill="none"
                stroke="#22d3ee"
                strokeWidth="2"
                points={buildPolylinePoints(positions, 400, 120)}
              />
            )}
          </svg>
        </div>

        <div className="rounded-xl border border-slate-800 bg-slate-900/40 p-3">
          <div className="mb-2 flex items-center justify-between text-xs">
            <span className="inline-flex items-center gap-1.5 font-semibold text-emerald-300">
              <Activity className="h-3.5 w-3.5" aria-hidden="true" />
              Angular Velocity (rad/s)
            </span>
            <span className="font-mono text-slate-300">
              {latest
                ? `${(latest.resources[0]?.state.angular_velocity_radians_per_second ?? 0).toFixed(3)} rad/s`
                : "—"}
            </span>
          </div>
          <svg
            aria-label="Angular velocity chart"
            viewBox="0 0 400 120"
            className="h-32 w-full rounded bg-slate-950"
          >
            {velocities.length > 0 && (
              <polyline
                fill="none"
                stroke="#34d399"
                strokeWidth="2"
                points={buildPolylinePoints(velocities, 400, 120)}
              />
            )}
          </svg>
        </div>
      </div>

      <div className="rounded-xl border border-slate-800 bg-slate-900/40 p-3">
        <h3 className="mb-2 text-xs font-semibold text-slate-400">
          2D Runtime Component Health Topology
        </h3>
        {latest && latest.resources.length > 0 ? (
          <div className="grid grid-cols-1 gap-2.5 md:grid-cols-2">
            {latest.resources.map((resource) => (
              <div
                key={resource.identity}
                className="rounded-lg border border-slate-800 bg-slate-950 p-3 text-xs"
              >
                <div className="flex items-center justify-between">
                  <span className="font-mono font-semibold text-slate-100">
                    {resource.identity}
                  </span>
                  <StatusBadge
                    tone={
                      resource.health_status === "healthy"
                        ? "success"
                        : resource.health_status === "degraded"
                          ? "warning"
                          : "error"
                    }
                  >
                    {resource.health_status}
                  </StatusBadge>
                </div>
                <p className="mt-1 font-mono text-slate-400">
                  lifecycle: {resource.lifecycle_state} · rev: {resource.state.revision}
                </p>
                {resource.health_summary && (
                  <p className="mt-1.5 inline-flex items-center gap-1 text-amber-300">
                    <AlertTriangle className="h-3.5 w-3.5" aria-hidden="true" />
                    {resource.health_summary}
                  </p>
                )}
              </div>
            ))}
          </div>
        ) : (
          <p className="text-xs text-slate-400">
            No telemetry samples received yet. Connect to `/api/v1/sessions/&lt;session&gt;/stream`
            over 127.0.0.1 or inject a local diagnostic sample above.
          </p>
        )}
      </div>
    </section>
  );
}
