import { z } from "zod";

export const TELEMETRY_SCHEMA_VERSION = "1" as const;

export const telemetryResourceSchema = z
  .object({
    identity: z.string().min(1),
    kind: z.string().min(1),
    lifecycle_state: z.string().min(1),
    health_status: z.enum(["unknown", "healthy", "degraded", "unhealthy"]),
    health_summary: z.string().nullable(),
    state: z
      .object({
        angular_position_radians: z.number().finite(),
        angular_velocity_radians_per_second: z.number().finite(),
        simulation_time_seconds: z.number().finite().nonnegative(),
        revision: z.number().int().nonnegative(),
      })
      .strict(),
  })
  .strict();

export const telemetryFrameSchema = z
  .object({
    schema_version: z.literal(TELEMETRY_SCHEMA_VERSION),
    session: z.string().min(1),
    sequence_number: z.number().int().positive(),
    timestamp_monotonic_ms: z.number().finite().nonnegative(),
    timestamp_utc: z.string().min(1),
    sampling_rate_hz: z.number().finite().positive(),
    buffer_limit: z.number().int().positive(),
    dropped_frames: z.number().int().nonnegative(),
    correlation_id: z.string().min(1),
    runtime_state: z.string().min(1),
    resources: z.array(telemetryResourceSchema),
  })
  .strict();

export const structuredLogRecordSchema = z
  .object({
    schema_version: z.literal(TELEMETRY_SCHEMA_VERSION),
    sequence_number: z.number().int().positive(),
    timestamp_utc: z.string().min(1),
    level: z.enum(["DEBUG", "INFO", "WARNING", "ERROR"]),
    source: z.string().min(1),
    correlation_id: z.string().min(1),
    fault_code: z.string().nullable(),
    message: z.string().min(1),
  })
  .strict();

export type TelemetryResource = z.infer<typeof telemetryResourceSchema>;
export type TelemetryFrame = z.infer<typeof telemetryFrameSchema>;
export type StructuredLogRecord = z.infer<typeof structuredLogRecordSchema>;

export interface SequenceGap {
  readonly expected: number;
  readonly received: number;
  readonly missingCount: number;
}

/**
 * Fixed-capacity ring buffer with deterministic drop-oldest backpressure (ADR 0002 v1.1).
 */
export class TelemetryRingBuffer<T> {
  private readonly items: T[] = [];
  private dropped = 0;
  readonly capacity: number;

  constructor(capacity = 120) {
    if (!Number.isInteger(capacity) || capacity <= 0) {
      throw new Error("TelemetryRingBuffer capacity must be a positive integer");
    }
    this.capacity = capacity;
  }

  get size(): number {
    return this.items.length;
  }

  get droppedCount(): number {
    return this.dropped;
  }

  push(item: T): boolean {
    let evicted = false;
    if (this.items.length >= this.capacity) {
      this.items.shift();
      this.dropped += 1;
      evicted = true;
    }
    this.items.push(item);
    return evicted;
  }

  toArray(): readonly T[] {
    return [...this.items];
  }

  clear(): void {
    this.items.length = 0;
    this.dropped = 0;
  }
}

/**
 * Explicit missing-data detector over monotonic `sequence_number`.
 * Gaps are surfaced to the operator and never silently interpolated.
 */
export class SequenceGapDetector {
  private lastSequence: number | null = null;
  private totalMissing = 0;
  private readonly observedGaps: SequenceGap[] = [];

  observe(sequenceNumber: number): SequenceGap | null {
    if (!Number.isInteger(sequenceNumber) || sequenceNumber <= 0) {
      throw new Error("sequenceNumber must be a positive integer");
    }
    if (this.lastSequence !== null && sequenceNumber > this.lastSequence + 1) {
      const gap: SequenceGap = {
        expected: this.lastSequence + 1,
        received: sequenceNumber,
        missingCount: sequenceNumber - (this.lastSequence + 1),
      };
      this.totalMissing += gap.missingCount;
      this.observedGaps.push(gap);
      this.lastSequence = sequenceNumber;
      return gap;
    }
    this.lastSequence = sequenceNumber;
    return null;
  }

  get missingCount(): number {
    return this.totalMissing;
  }

  get gaps(): readonly SequenceGap[] {
    return [...this.observedGaps];
  }

  reset(): void {
    this.lastSequence = null;
    this.totalMissing = 0;
    this.observedGaps.length = 0;
  }
}

/**
 * Bounded exponential backoff for SSE stream reconnection.
 */
export function computeReconnectDelayMs(
  attempt: number,
  baseMs = 500,
  maxMs = 10_000,
): number {
  const safeAttempt = Math.max(0, Math.floor(attempt));
  return Math.min(maxMs, baseMs * 2 ** safeAttempt);
}

export interface ParsedSseEvent {
  readonly id: string;
  readonly event: string;
  readonly data: string;
}

/**
 * Parses complete `\n\n`-delimited SSE frames from an incremental text buffer.
 */
export function parseSseEvents(buffer: string): {
  readonly events: readonly ParsedSseEvent[];
  readonly remainder: string;
} {
  const normalized = buffer.replaceAll("\r\n", "\n");
  const blocks = normalized.split("\n\n");
  const remainder = blocks.pop() ?? "";
  const events: ParsedSseEvent[] = [];

  for (const block of blocks) {
    if (block.trim().length === 0) continue;
    let id = "";
    let event = "message";
    const dataLines: string[] = [];
    for (const line of block.split("\n")) {
      if (line.startsWith("id:")) id = line.slice(3).trim();
      else if (line.startsWith("event:")) event = line.slice(6).trim();
      else if (line.startsWith("data:")) dataLines.push(line.slice(5).trim());
    }
    if (dataLines.length > 0) {
      events.push({ id, event, data: dataLines.join("\n") });
    }
  }
  return { events, remainder };
}

export interface FaultDiagnosis {
  readonly faultCode: string;
  readonly severity: "warning" | "error";
  readonly title: string;
  readonly likelyCauses: readonly string[];
  readonly recommendedChecks: readonly string[];
}

export function classifyFault(reason: string): FaultDiagnosis {
  const normalized = reason.trim().toLowerCase();
  if (normalized.includes("deadline exceeded") || normalized.includes("operation_deadline_exceeded")) {
    return {
      faultCode: "OPERATION_DEADLINE_EXCEEDED",
      severity: "error",
      title: "Runtime operation deadline exceeded",
      likelyCauses: [
        "Driver or device I/O exceeded configured RB-1 operation deadline.",
        "Host CPU contention or stalled serial/CAN bus response.",
      ],
      recommendedChecks: [
        "Filter structured logs by Correlation-ID to inspect the offending resource.",
        "Verify device wiring and timeout settings before restarting.",
      ],
    };
  }
  if (normalized.includes("backend unavailable") || normalized.includes("backend_unavailable")) {
    return {
      faultCode: "BACKEND_UNAVAILABLE",
      severity: "error",
      title: "Resource backend unavailable",
      likelyCauses: [
        "Device disconnected or driver initialization failed.",
        "OS permission error on serial/USB/CAN port.",
      ],
      recommendedChecks: [
        "Inspect Runtime process logs and verify local device permissions.",
        "Run device preflight before re-enabling the component.",
      ],
    };
  }
  if (normalized.includes("safe-stop failed") || normalized.includes("safe_stop_failed")) {
    return {
      faultCode: "SAFE_STOP_FAILED",
      severity: "error",
      title: "Best-effort software safe-stop failed",
      likelyCauses: [
        "Actuator stopped acknowledging commands during safe-stop transition.",
        "Communication link dropped before zero-velocity command completed.",
      ],
      recommendedChecks: [
        "Verify physical safety via external hardware E-stop.",
        "Inspect fault timeline before re-commanding actuators.",
      ],
    };
  }
  if (normalized.includes("session_not_running") || normalized.includes("session_stopped")) {
    return {
      faultCode: "RUNTIME_SESSION_STOPPED",
      severity: "warning",
      title: "Observed Runtime session stopped",
      likelyCauses: ["The foreground `hiyelx runtime start` owner exited or was stopped."],
      recommendedChecks: ["Start a new local Runtime session or select another active session."],
    };
  }
  return {
    faultCode: "RUNTIME_DIAGNOSTIC_WARNING",
    severity: "warning",
    title: "Runtime diagnostic condition reported",
    likelyCauses: ["Sanitized runtime condition or transient observation interruption."],
    recommendedChecks: ["Inspect structured logs and verify Runtime health status."],
  };
}
