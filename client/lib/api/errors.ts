/**
 * Axios error normalization.
 *
 * Spec section 37: the UI must show actionable, human-readable messages and
 * must never surface raw transport failures or backend internals. Every error
 * that escapes the API layer is converted into an `ApiError` so that components
 * and TanStack Query retry policies can reason about a single, stable shape.
 */
import axios from "axios";
import type { ApiErrorBody } from "@/types/api";

export type ApiErrorKind =
  /** No response received: offline, DNS failure, CORS, connection refused. */
  | "network"
  /** The request exceeded the configured timeout. */
  | "timeout"
  /** The request was cancelled by an AbortSignal or unmount. */
  | "canceled"
  /** 401 - not authenticated. */
  | "unauthorized"
  /** 403 - authenticated but not permitted (spec section 56). */
  | "forbidden"
  /** 404 - resource does not exist. */
  | "not_found"
  /** 422 - request failed backend validation. */
  | "validation"
  /** 429 - rate limited (spec section 60). */
  | "rate_limited"
  /** Any other 4xx. */
  | "client"
  /** Any 5xx. */
  | "server"
  /** Anything that is not an Axios error at all. */
  | "unknown";

/** Messages safe to render directly in the UI. */
const FALLBACK_MESSAGES: Record<ApiErrorKind, string> = {
  network: "Unable to reach the server. Check your connection and try again.",
  timeout: "The request took too long to complete. Please try again.",
  canceled: "The request was cancelled.",
  unauthorized: "Your session has expired. Please sign in again.",
  forbidden: "You do not have permission to view this information.",
  not_found: "The requested information could not be found.",
  validation: "Some of the supplied values were not valid.",
  rate_limited: "Too many requests. Please wait a moment and try again.",
  client: "The request could not be completed.",
  server: "The server encountered a problem. Please try again shortly.",
  unknown: "Something went wrong. Please try again.",
};

export class ApiError extends Error {
  readonly kind: ApiErrorKind;
  /** HTTP status, or `undefined` when no response was received. */
  readonly status?: number;
  /** Stable backend error code from spec section 68, when present. */
  readonly code?: string;
  /** Field-level validation messages, present for `validation` errors. */
  readonly details?: Record<string, string[]>;
  /** Seconds to wait before retrying, from the `Retry-After` header on a 429. */
  readonly retryAfterSeconds?: number;

  constructor(init: {
    kind: ApiErrorKind;
    message: string;
    status?: number;
    code?: string;
    details?: Record<string, string[]>;
    retryAfterSeconds?: number;
    cause?: unknown;
  }) {
    super(init.message, { cause: init.cause });
    this.name = "ApiError";
    this.kind = init.kind;
    this.status = init.status;
    this.code = init.code;
    this.details = init.details;
    this.retryAfterSeconds = init.retryAfterSeconds;
  }

  /** True when retrying the same request could plausibly succeed. */
  get isRetryable(): boolean {
    return this.kind === "network" || this.kind === "timeout" || this.kind === "server";
  }

  /** True when the user needs to re-authenticate. */
  get isAuthError(): boolean {
    return this.kind === "unauthorized";
  }
}

function kindForStatus(status: number): ApiErrorKind {
  switch (status) {
    case 401:
      return "unauthorized";
    case 403:
      return "forbidden";
    case 404:
      return "not_found";
    case 422:
      return "validation";
    case 429:
      return "rate_limited";
    default:
      return status >= 500 ? "server" : "client";
  }
}

/** Narrows an unknown response body to the documented error envelope. */
function readErrorBody(data: unknown): ApiErrorBody["error"] | undefined {
  if (typeof data !== "object" || data === null || !("error" in data)) return undefined;

  const { error } = data as { error: unknown };
  if (typeof error !== "object" || error === null) return undefined;

  const { code, message, details } = error as Record<string, unknown>;
  if (typeof code !== "string" || typeof message !== "string") return undefined;

  return {
    code,
    message,
    details:
      typeof details === "object" && details !== null
        ? (details as Record<string, string[]>)
        : undefined,
  };
}

function readRetryAfter(value: unknown): number | undefined {
  if (typeof value !== "string") return undefined;
  const seconds = Number.parseInt(value, 10);
  return Number.isFinite(seconds) && seconds >= 0 ? seconds : undefined;
}

/** Converts any thrown value into an `ApiError`. Never throws. */
export function normalizeError(error: unknown): ApiError {
  if (error instanceof ApiError) return error;

  if (axios.isCancel(error)) {
    return new ApiError({ kind: "canceled", message: FALLBACK_MESSAGES.canceled, cause: error });
  }

  if (axios.isAxiosError(error)) {
    if (error.code === "ECONNABORTED" || error.code === "ETIMEDOUT") {
      return new ApiError({ kind: "timeout", message: FALLBACK_MESSAGES.timeout, cause: error });
    }

    if (!error.response) {
      return new ApiError({ kind: "network", message: FALLBACK_MESSAGES.network, cause: error });
    }

    const { status, data, headers } = error.response;
    const kind = kindForStatus(status);
    const body = readErrorBody(data);

    return new ApiError({
      kind,
      // Prefer the backend's message: it is written to be user-safe.
      message: body?.message ?? FALLBACK_MESSAGES[kind],
      status,
      code: body?.code,
      details: body?.details,
      retryAfterSeconds:
        kind === "rate_limited" ? readRetryAfter(headers?.["retry-after"]) : undefined,
      cause: error,
    });
  }

  return new ApiError({
    kind: "unknown",
    message: FALLBACK_MESSAGES.unknown,
    cause: error,
  });
}

/** Convenience guard for use in components and error boundaries. */
export function isApiError(error: unknown): error is ApiError {
  return error instanceof ApiError;
}
