import { describe, expect, it } from "vitest";
import {
  CAPABILITY_HEADER,
  StudioApiClient,
  StudioApiError,
  assertLoopbackOrigin,
  parseStudioLaunchUrl,
} from "@hiyelx/api-client";
import type { StructuredLogRecord, TelemetryFrame } from "@hiyelx/telemetry";

const VALID_CAPABILITY = "A".repeat(43);
const VALID_ORIGIN = "http://127.0.0.1:43123";

function makeJsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json; charset=utf-8" },
  });
}

describe("@hiyelx/api-client", () => {
  it("enforces strict 127.0.0.1 loopback origin and #capability fragment parsing", () => {
    expect(assertLoopbackOrigin(VALID_ORIGIN)).toBe(VALID_ORIGIN);
    for (const bad of [
      "http://0.0.0.0:43123",
      "http://localhost:43123",
      "https://127.0.0.1:43123",
      "http://example.com:80",
      "http://127.0.0.1:0",
    ]) {
      expect(() => assertLoopbackOrigin(bad)).toThrow(StudioApiError);
    }

    const parsed = parseStudioLaunchUrl(`${VALID_ORIGIN}/live#capability=${VALID_CAPABILITY}`);
    expect(parsed).toEqual({ origin: VALID_ORIGIN, capability: VALID_CAPABILITY });

    expect(() => parseStudioLaunchUrl(`${VALID_ORIGIN}/live#token=${VALID_CAPABILITY}`)).toThrow(
      StudioApiError,
    );
  });

  it("sends X-HIYELX-Studio-Capability header and validates meta, runtime/info, and sessions", async () => {
    const seenHeaders: Record<string, string>[] = [];
    const fetchMock: typeof fetch = async (input, init) => {
      const url = typeof input === "string" ? input : input.toString();
      seenHeaders.push((init?.headers ?? {}) as Record<string, string>);
      if (url.endsWith("/api/v1/meta")) {
        return makeJsonResponse({
          app_version: "0.2.0a1",
          host_version: "1",
          ready: true,
          schema_version: "1",
        });
      }
      if (url.endsWith("/api/v1/runtime/info")) {
        return makeJsonResponse({
          package_version: "0.2.0a1",
          registered_models: [
            { capabilities: ["can_set_velocity"], category: "actuator", model: "mock.motor" },
          ],
          schema_version: "1",
          supported_config_schemas: ["1", "2"],
        });
      }
      if (url.endsWith("/api/v1/sessions")) {
        return makeJsonResponse({ schema_version: "1", sessions: ["alpha"] });
      }
      return makeJsonResponse(
        { error: { code: "not_found", message: "Studio resource was not found." }, schema_version: "1" },
        404,
      );
    };

    const client = new StudioApiClient({
      origin: VALID_ORIGIN,
      capability: VALID_CAPABILITY,
      fetchImpl: fetchMock,
    });

    const meta = await client.fetchMeta();
    expect(meta.app_version).toBe("0.2.0a1");
    const info = await client.fetchRuntimeInfo();
    expect(info.registered_models[0]?.model).toBe("mock.motor");
    const sessions = await client.fetchSessions();
    expect(sessions).toEqual(["alpha"]);

    expect(seenHeaders).toHaveLength(3);
    for (const headers of seenHeaders) {
      expect(headers[CAPABILITY_HEADER]).toBe(VALID_CAPABILITY);
    }
  });

  it("consumes authenticated SSE telemetry and diagnostic events over fetch without query tokens", async () => {
    const frame: TelemetryFrame = {
      schema_version: "1",
      session: "alpha",
      sequence_number: 1,
      timestamp_monotonic_ms: 100.5,
      timestamp_utc: "2026-11-24T19:00:00Z",
      sampling_rate_hz: 2.0,
      buffer_limit: 256,
      dropped_frames: 0,
      correlation_id: "alpha-seq-1",
      runtime_state: "running",
      resources: [
        {
          identity: "sim_motor",
          kind: "motor",
          lifecycle_state: "running",
          health_status: "degraded",
          health_summary: "deadline exceeded during motor command",
          state: {
            angular_position_radians: 0.42,
            angular_velocity_radians_per_second: 0.1,
            simulation_time_seconds: 1.0,
            revision: 3,
          },
        },
      ],
    };
    const diag: StructuredLogRecord = {
      schema_version: "1",
      sequence_number: 1,
      timestamp_utc: "2026-11-24T19:00:00Z",
      level: "ERROR",
      source: "sim_motor",
      correlation_id: "alpha-seq-1",
      fault_code: "OPERATION_DEADLINE_EXCEEDED",
      message: "deadline exceeded during motor command",
    };

    const ssePayload =
      `id: 1\nevent: telemetry\ndata: ${JSON.stringify(frame)}\n\n` +
      `id: 1\nevent: diagnostic\ndata: ${JSON.stringify(diag)}\n\n`;
    const encoder = new TextEncoder();

    const fetchMock: typeof fetch = async (input, init) => {
      const url = typeof input === "string" ? input : input.toString();
      expect(url).toBe(`${VALID_ORIGIN}/api/v1/sessions/alpha/stream`);
      expect(url).not.toContain("capability");
      expect((init?.headers as Record<string, string>)[CAPABILITY_HEADER]).toBe(VALID_CAPABILITY);

      const stream = new ReadableStream<Uint8Array>({
        start(controller) {
          controller.enqueue(encoder.encode(ssePayload.slice(0, 40)));
          controller.enqueue(encoder.encode(ssePayload.slice(40)));
          controller.close();
        },
      });
      return new Response(stream, {
        status: 200,
        headers: { "Content-Type": "text/event-stream; charset=utf-8" },
      });
    };

    const client = new StudioApiClient({
      origin: VALID_ORIGIN,
      capability: VALID_CAPABILITY,
      fetchImpl: fetchMock,
    });

    const receivedFrames: TelemetryFrame[] = [];
    const receivedLogs: StructuredLogRecord[] = [];
    const statuses: string[] = [];

    await client.subscribeSessionStream(
      "alpha",
      {
        onStatus: (s) => statuses.push(s),
        onTelemetry: (f) => receivedFrames.push(f),
        onDiagnostic: (d) => receivedLogs.push(d),
      },
      { maxReconnectAttempts: 0 },
    );

    expect(statuses).toEqual(["connecting", "live", "disconnected"]);
    expect(receivedFrames).toHaveLength(1);
    expect(receivedFrames[0]?.sequence_number).toBe(1);
    expect(receivedLogs).toHaveLength(1);
    expect(receivedLogs[0]?.fault_code).toBe("OPERATION_DEADLINE_EXCEEDED");
  });

  it("stops immediately without retrying on 403 request_rejected", async () => {
    let calls = 0;
    const fetchMock: typeof fetch = async () => {
      calls += 1;
      return makeJsonResponse(
        { error: { code: "request_rejected", message: "Studio request was rejected." }, schema_version: "1" },
        403,
      );
    };

    const client = new StudioApiClient({
      origin: VALID_ORIGIN,
      capability: VALID_CAPABILITY,
      fetchImpl: fetchMock,
    });

    const errors: StudioApiError[] = [];
    await client.subscribeSessionStream(
      "alpha",
      {
        onTelemetry: () => undefined,
        onError: (e) => errors.push(e),
      },
      { maxReconnectAttempts: 3, reconnectBaseMs: 1 },
    );

    expect(calls).toBe(1);
    expect(errors[0]?.code).toBe("request_rejected");
  });
});
