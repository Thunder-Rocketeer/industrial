/**
 * The single Axios instance for the whole application.
 *
 * Spec section 15 and principle 4: do not construct ad-hoc Axios instances in
 * components or feature modules. Every request goes through this client so that
 * base URL, credentials, timeouts, correlation IDs and error normalization are
 * applied uniformly and in one place.
 *
 * Authentication note (spec sections 55.3 / 55.4): the backend issues the
 * session as an HTTP-only, Secure, SameSite cookie. The browser attaches it
 * automatically because `withCredentials` is enabled. No token is ever read
 * from or written to JavaScript-accessible storage, so there is deliberately no
 * Authorization-header interceptor here.
 */
import axios, {
  type AxiosInstance,
  type AxiosRequestConfig,
  type InternalAxiosRequestConfig,
} from "axios";

import { env } from "@/lib/env";
import { normalizeError } from "@/lib/api/errors";

/** Header used to correlate a browser request with backend logs (spec section 28). */
export const CORRELATION_ID_HEADER = "X-Request-ID";

function createCorrelationId(): string {
  // `crypto.randomUUID` is available in all supported browsers and in Node 19+,
  // but is absent in insecure contexts, so fall back to a cheap random string.
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    return crypto.randomUUID();
  }
  return `req-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
}

function attachRequestMetadata(config: InternalAxiosRequestConfig): InternalAxiosRequestConfig {
  config.headers.set("Accept", "application/json");
  if (!config.headers.has(CORRELATION_ID_HEADER)) {
    config.headers.set(CORRELATION_ID_HEADER, createCorrelationId());
  }
  return config;
}

export const apiClient: AxiosInstance = axios.create({
  baseURL: env.NEXT_PUBLIC_API_BASE_URL,
  timeout: env.NEXT_PUBLIC_API_TIMEOUT_MS,
  // Required for the HTTP-only session cookie. The backend must therefore send
  // an explicit CORS origin, never a wildcard (spec section 61).
  withCredentials: true,
  headers: { "Content-Type": "application/json" },
  // Serialize array params as `?shift=A&shift=B`, which is what FastAPI expects
  // for `Query(list[str])` parameters.
  paramsSerializer: { indexes: null },
});

apiClient.interceptors.request.use(attachRequestMetadata);

/**
 * Callbacks invoked once when the session is found to have ended.
 *
 * Registered by the auth layer rather than imported here, so this module stays
 * free of React and of any particular router.
 */
type SessionExpiredHandler = () => void;
const sessionExpiredHandlers = new Set<SessionExpiredHandler>();

/** Register a callback for session expiry. Returns an unsubscribe function. */
export function onSessionExpired(handler: SessionExpiredHandler): () => void {
  sessionExpiredHandlers.add(handler);
  return () => sessionExpiredHandlers.delete(handler);
}

/**
 * Guards against a burst of notifications.
 *
 * A dashboard makes several concurrent requests. When a session expires they
 * all return 401 at once, and without this every one would trigger a redirect
 * (spec section 27: "avoid an infinite redirect loop"). The first notification
 * wins; the rest are suppressed until the window passes.
 */
let lastSessionExpiryNotice = 0;
const SESSION_EXPIRY_NOTICE_INTERVAL_MS = 5_000;

function notifySessionExpired(): void {
  const now = Date.now();
  if (now - lastSessionExpiryNotice < SESSION_EXPIRY_NOTICE_INTERVAL_MS) {
    return;
  }
  lastSessionExpiryNotice = now;
  for (const handler of sessionExpiredHandlers) {
    handler();
  }
}

apiClient.interceptors.response.use(
  (response) => response,
  (error: unknown) => {
    const normalized = normalizeError(error);

    // A 401 on the session-check endpoint is the *expected* answer for an
    // anonymous visitor. Treating it as an expiry would make every signed-out
    // page load announce that a session had ended.
    const url = (error as { config?: { url?: string } })?.config?.url ?? "";
    const isSessionProbe = url.includes("/auth/me") || url.includes("/auth/status");

    if (normalized.isAuthError && !isSessionProbe) {
      notifySessionExpired();
    }

    // Reject with a normalized ApiError so no raw AxiosError escapes this module.
    return Promise.reject(normalized);
  },
);

/**
 * Typed request helpers.
 *
 * Feature modules under `lib/api/` build on these rather than touching
 * `apiClient` directly, which keeps the unwrapping of `response.data`
 * consistent and makes the return type explicit at every call site.
 */

export async function get<TResponse>(url: string, config?: AxiosRequestConfig): Promise<TResponse> {
  const response = await apiClient.get<TResponse>(url, config);
  return response.data;
}

export async function post<TResponse, TBody = unknown>(
  url: string,
  body?: TBody,
  config?: AxiosRequestConfig,
): Promise<TResponse> {
  const response = await apiClient.post<TResponse>(url, body, config);
  return response.data;
}

export async function put<TResponse, TBody = unknown>(
  url: string,
  body?: TBody,
  config?: AxiosRequestConfig,
): Promise<TResponse> {
  const response = await apiClient.put<TResponse>(url, body, config);
  return response.data;
}

export async function patch<TResponse, TBody = unknown>(
  url: string,
  body?: TBody,
  config?: AxiosRequestConfig,
): Promise<TResponse> {
  const response = await apiClient.patch<TResponse>(url, body, config);
  return response.data;
}

export async function del<TResponse>(url: string, config?: AxiosRequestConfig): Promise<TResponse> {
  const response = await apiClient.delete<TResponse>(url, config);
  return response.data;
}
