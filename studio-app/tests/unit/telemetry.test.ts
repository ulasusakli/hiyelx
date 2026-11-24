import { describe, expect, it } from "vitest";
import {
  SequenceGapDetector,
  TelemetryRingBuffer,
  classifyFault,
  computeReconnectDelayMs,
  parseSseEvents,
  telemetryFrameSchema,
} from "@hiyelx/telemetry";

describe("P7.2 TypeScript telemetry engine", () => {
  it("enforces ring buffer drop-oldest backpressure and explicit sequence gap detection", () => {
    const buffer = new TelemetryRingBuffer<number>(3);
    expect(buffer.push(1)).toBe(false);
    expect(buffer.push(2)).toBe(false);
    expect(buffer.push(3)).toBe(false);
    expect(buffer.push(4)).toBe(true);
    expect(buffer.toArray()).toEqual([2, 3, 4]);
    expect(buffer.droppedCount).toBe(1);

    const detector = new SequenceGapDetector();
    expect(detector.observe(1)).toBeNull();
    expect(detector.observe(2)).toBeNull();
    const gap = detector.observe(5);
    expect(gap).toEqual({ expected: 3, received: 5, missingCount: 2 });
    expect(detector.missingCount).toBe(2);
  });

  it("parses incremental SSE chunks, validates telemetry frames, computes bounded backoff, and classifies faults", () => {
    expect(computeReconnectDelayMs(0, 500, 5000)).toBe(500);
    expect(computeReconnectDelayMs(1, 500, 5000)).toBe(1000);
    expect(computeReconnectDelayMs(10, 500, 5000)).toBe(5000);

    const frame = {
      buffer_limit: 256,
      correlation_id: "alpha-seq-1",
      dropped_frames: 0,
      resources: [
        {
          health_status: "healthy",
          health_summary: null,
          identity: "sim_motor",
          kind: "motor",
          lifecycle_state: "running",
          state: {
            angular_position_radians: 0.5,
            angular_velocity_radians_per_second: 1.0,
            revision: 2,
            simulation_time_seconds: 1.5,
          },
        },
      ],
      runtime_state: "running",
      sampling_rate_hz: 2.0,
      schema_version: "1",
      sequence_number: 1,
      session: "alpha",
      timestamp_monotonic_ms: 1234.5,
      timestamp_utc: "2026-11-24T16:00:00Z",
    };

    const chunk = `id: 1\nevent: telemetry\ndata: ${JSON.stringify(frame)}\n\nid: 2\nevent: telemetry\ndata: {"partial":`;
    const parsed = parseSseEvents(chunk);
    expect(parsed.events).toHaveLength(1);
    expect(parsed.events[0]?.event).toBe("telemetry");
    expect(parsed.remainder).toContain("id: 2");

    const validated = telemetryFrameSchema.parse(JSON.parse(parsed.events[0]?.data ?? "{}"));
    expect(validated.sequence_number).toBe(1);

    expect(classifyFault("deadline exceeded during motor command").faultCode).toBe(
      "OPERATION_DEADLINE_EXCEEDED",
    );
    expect(classifyFault("safe-stop failed during shutdown").faultCode).toBe("SAFE_STOP_FAILED");
  });
});
