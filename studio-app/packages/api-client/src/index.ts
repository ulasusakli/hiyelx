import { z } from "zod";
import {
  computeReconnectDelayMs,
  parseSseEvents,
  structuredLogRecordSchema,
  telemetryFrameSchema,
  type StructuredLogRecord,
  type TelemetryFrame,
} from "@hiyelx/telemetry";

export const CAPABILITY_HEADER = "X-HIYELX-Studio-Capability" as const;
const LOOPBACK_ORIGIN_RE = /^http:\/\/127\.0\.0\.1:([0-9]{1,5})$/;
const CAPABILITY_RE = /^[A-Za-z0-9_-]{43}$/;
const SESSION_ID_RE = /^[a-z0-9][a-z0-9_-]{0,47}$/;

export class StudioApiError extends Error {
  readonly status: number;
  readonly code: string;

  constructor(status: number, code: string, message: string) {
    super(message);
    this.name = "StudioApiError";
    this.status = status;
    this.code = code;
  }
}

export function assertLoopbackOrigin(origin: string): string {
  const match = LOOPBACK_ORIGIN_RE.exec(origin.trim());
  if (match === null) {
    throw new StudioApiError(
      0,
      "invalid_origin",
      "Studio Host origin must strictly match http://127.0.0.1:<port>.",
    );
  }
  const port = Number(match[1]);
  if (!Number.isInteger(port) || port < 1 || port > 65535) {
    throw new StudioApiError(0, "invalid_origin", "Studio Host port is out of range (1..65535).");
  }
  return `http://127.0.0.1:${port}`;
}

export function assertCapabilityToken(token: string): string {
  const trimmed = token.trim();
  if (!CAPABILITY_RE.test(trimmed)) {
    throw new StudioApiError(
      0,
      "invalid_capability",
      "Capability token must be a 43-character base64url secret.",
    );
  }
  return trimmed;
}

export function assertSessionId(session: string): string {
  if (!SESSION_ID_RE.test(session)) {
    throw new StudioApiError(0, "invalid_request", `Invalid session id "${session}".`);
  }
  return session;
}

export function parseStudioLaunchUrl(launchUrl: string): {
  readonly origin: string;
  readonly capability: string;
} {
  let parsed: URL;
  try {
    parsed = new URL(launchUrl.trim());
  } catch {
    throw new StudioApiError(0, "invalid_launch_url", "Launch URL could not be parsed.");
  }
  const origin = assertLoopbackOrigin(parsed.origin);
  const hash = parsed.hash;
  if (!hash.startsWith("#capability=")) {
    throw new StudioApiError(
      0,
      "invalid_capability",
      "Launch URL must include #capability=<token>.",
    );
  }
  const capability = assertCapabilityToken(hash.slice("#capability=".length));
  return { origin, capability };
}

export const hostMetaSchema = z
  .object({
    app_version: z.string().min(1),
    host_version: z.literal("1"),
    ready: z.literal(true),
    schema_version: z.literal("1"),
  })
  .strict();

export const runtimeInfoSchema = z
  .object({
    package_version: z.string().min(1),
    registered_models: z.array(
      z
        .object({
          capabilities: z.array(z.string().min(1)),
          category: z.string().min(1),
          model: z.string().min(1),
        })
        .strict(),
    ),
    schema_version: z.literal("1"),
    supported_config_schemas: z.array(z.string().min(1)).min(1),
  })
  .strict();

export const sessionsResponseSchema = z
  .object({
    schema_version: z.literal("1"),
    sessions: z.array(z.string().regex(SESSION_ID_RE)),
  })
  .strict();

const hostErrorEnvelopeSchema = z
  .object({
    error: z
      .object({
        code: z.string().min(1),
        message: z.string().min(1),
      })
      .strict(),
    schema_version: z.literal("1"),
  })
  .strict();

export type HostMeta = z.infer<typeof hostMetaSchema>;
export type StudioRuntimeInfo = z.infer<typeof runtimeInfoSchema>;
export type SessionsResponse = z.infer<typeof sessionsResponseSchema>;

export interface StudioApiClientOptions {
  readonly origin: string;
  readonly capability: string;
  readonly fetchImpl?: typeof fetch;
}

export interface SessionStreamCallbacks {
  readonly onStatus?: (status: "connecting" | "live" | "reconnecting" | "disconnected") => void;
  readonly onTelemetry: (frame: TelemetryFrame) => void;
  readonly onDiagnostic?: (record: StructuredLogRecord) => void;
  readonly onError?: (error: StudioApiError) => void;
}

export interface SessionStreamOptions {
  readonly signal?: AbortSignal;
  readonly maxReconnectAttempts?: number;
  readonly reconnectBaseMs?: number;
  readonly reconnectMaxMs?: number;
}

const NON_RETRYABLE_ERROR_CODES = new Set([
  "request_rejected",
  "host_rejected",
  "invalid_request",
  "session_not_running",
  "preview_unsupported",
  "schema_unsupported",
  "method_not_allowed",
]);

export class StudioApiClient {
  readonly origin: string;
  private readonly capability: string;
  private readonly fetchImpl: typeof fetch;

  constructor(options: StudioApiClientOptions) {
    this.origin = assertLoopbackOrigin(options.origin);
    this.capability = assertCapabilityToken(options.capability);
    this.fetchImpl = options.fetchImpl ?? globalThis.fetch.bind(globalThis);
  }

  private async getJson<T>(path: string, schema: z.ZodType<T>, signal?: AbortSignal): Promise<T> {
    let response: Response;
    try {
      response = await this.fetchImpl(`${this.origin}${path}`, {
        method: "GET",
        cache: "no-store",
        credentials: "omit",
        referrerPolicy: "no-referrer",
        headers: {
          [CAPABILITY_HEADER]: this.capability,
        },
        signal,
      });
    } catch {
      throw new StudioApiError(0, "host_disconnected", "Connection to local Studio Host failed.");
    }

    let document: unknown;
    try {
      document = await response.json();
    } catch {
      throw new StudioApiError(
        response.status,
        "invalid_response",
        "Studio Host returned malformed JSON.",
      );
    }

    if (!response.ok) {
      const parsedError = hostErrorEnvelopeSchema.safeParse(document);
      if (parsedError.success) {
        throw new StudioApiError(
          response.status,
          parsedError.data.error.code,
          parsedError.data.error.message,
        );
      }
      throw new StudioApiError(
        response.status,
        "application_error",
        `Studio Host returned HTTP ${response.status}.`,
      );
    }

    const parsed = schema.safeParse(document);
    if (!parsed.success) {
      const version =
        document !== null && typeof document === "object" && "schema_version" in document
          ? (document as Record<string, unknown>)["schema_version"]
          : undefined;
      if (version !== undefined && version !== "1") {
        throw new StudioApiError(
          422,
          "schema_unsupported",
          `Unsupported Studio API schema_version "${String(version)}".`,
        );
      }
      throw new StudioApiError(
        response.status,
        "invalid_response",
        "Studio Host response failed strict schema validation.",
      );
    }
    return parsed.data;
  }

  async fetchMeta(signal?: AbortSignal): Promise<HostMeta> {
    return this.getJson("/api/v1/meta", hostMetaSchema, signal);
  }

  async fetchRuntimeInfo(signal?: AbortSignal): Promise<StudioRuntimeInfo> {
    return this.getJson("/api/v1/runtime/info", runtimeInfoSchema, signal);
  }

  async fetchSessions(signal?: AbortSignal): Promise<readonly string[]> {
    const doc = await this.getJson("/api/v1/sessions", sessionsResponseSchema, signal);
    return doc.sessions;
  }

  /**
   * Connects to `GET /api/v1/sessions/{session}/stream` via authenticated `fetch` streaming
   * (sending `X-HIYELX-Studio-Capability` in headers, never in URL query strings).
   */
  async subscribeSessionStream(
    session: string,
    callbacks: SessionStreamCallbacks,
    options: SessionStreamOptions = {},
  ): Promise<void> {
    const validSession = assertSessionId(session);
    const maxAttempts = options.maxReconnectAttempts ?? 3;
    const baseMs = options.reconnectBaseMs ?? 500;
    const maxMs = options.reconnectMaxMs ?? 10_000;
    const signal = options.signal;

    let attempt = 0;

    while (!signal?.aborted) {
      callbacks.onStatus?.(attempt === 0 ? "connecting" : "reconnecting");
      let response: Response;
      try {
        response = await this.fetchImpl(
          `${this.origin}/api/v1/sessions/${validSession}/stream`,
          {
            method: "GET",
            cache: "no-store",
            credentials: "omit",
            referrerPolicy: "no-referrer",
            headers: {
              Accept: "text/event-stream",
              [CAPABILITY_HEADER]: this.capability,
            },
            signal,
          },
        );
      } catch {
        if (signal?.aborted) {
          callbacks.onStatus?.("disconnected");
          return;
        }
        const disconnectErr = new StudioApiError(
          0,
          "host_disconnected",
          "Lost connection to Studio Host SSE stream.",
        );
        callbacks.onError?.(disconnectErr);
        if (attempt >= maxAttempts) {
          callbacks.onStatus?.("disconnected");
          return;
        }
        await waitWithAbort(computeReconnectDelayMs(attempt, baseMs, maxMs), signal);
        attempt += 1;
        continue;
      }

      if (!response.ok) {
        let errorCode = "application_error";
        let errorMessage = `Studio Host returned HTTP ${response.status}.`;
        try {
          const doc: unknown = await response.json();
          const parsedErr = hostErrorEnvelopeSchema.safeParse(doc);
          if (parsedErr.success) {
            errorCode = parsedErr.data.error.code;
            errorMessage = parsedErr.data.error.message;
          }
        } catch {
          // Keep sanitized fallback message.
        }
        const apiError = new StudioApiError(response.status, errorCode, errorMessage);
        callbacks.onError?.(apiError);
        if (NON_RETRYABLE_ERROR_CODES.has(errorCode) || attempt >= maxAttempts) {
          callbacks.onStatus?.("disconnected");
          return;
        }
        await waitWithAbort(computeReconnectDelayMs(attempt, baseMs, maxMs), signal);
        attempt += 1;
        continue;
      }

      if (!response.body) {
        callbacks.onError?.(
          new StudioApiError(500, "invalid_response", "SSE response had no readable stream body."),
        );
        callbacks.onStatus?.("disconnected");
        return;
      }

      attempt = 0;
      callbacks.onStatus?.("live");
      const reader = response.body.getReader();
      const decoder = new TextDecoder("utf-8");
      let buffer = "";

      try {
        while (!signal?.aborted) {
          const { done, value } = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, { stream: true });
          const { events, remainder } = parseSseEvents(buffer);
          buffer = remainder;

          for (const sseEvent of events) {
            let parsedJson: unknown;
            try {
              parsedJson = JSON.parse(sseEvent.data);
            } catch {
              continue;
            }
            if (sseEvent.event === "telemetry") {
              const frame = telemetryFrameSchema.safeParse(parsedJson);
              if (frame.success) {
                callbacks.onTelemetry(frame.data);
              }
            } else if (sseEvent.event === "diagnostic") {
              const log = structuredLogRecordSchema.safeParse(parsedJson);
              if (log.success) {
                callbacks.onDiagnostic?.(log.data);
              }
            }
          }
        }
      } catch {
        if (signal?.aborted) {
          callbacks.onStatus?.("disconnected");
          return;
        }
      } finally {
        reader.releaseLock();
      }

      // Clean EOF from server (e.g., session stopped or bounded stream finished).
      callbacks.onStatus?.("disconnected");
      return;
    }

    callbacks.onStatus?.("disconnected");
  }
}

function waitWithAbort(ms: number, signal?: AbortSignal): Promise<void> {
  return new Promise((resolve) => {
    if (signal?.aborted) {
      resolve();
      return;
    }
    const timer = globalThis.setTimeout(() => {
      signal?.removeEventListener("abort", onAbort);
      resolve();
    }, ms);
    function onAbort() {
      globalThis.clearTimeout(timer);
      resolve();
    }
    signal?.addEventListener("abort", onAbort, { once: true });
  });
}
