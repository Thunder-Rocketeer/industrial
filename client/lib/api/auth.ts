/**
 * Authentication API calls.
 *
 * Built on the centralized Axios client from Phase 1, which already sends
 * `withCredentials: true` -- the session cookie travels automatically and is
 * never touched by this code (spec section 24).
 *
 * The CSRF token is the one piece of auth state JavaScript does handle. It is
 * deliberately readable, because the double-submit pattern needs the frontend
 * to echo it in a header; it is not a session secret.
 */
import { get, post } from "@/lib/api/client";
import type { ApiEnvelope } from "@/types/api";
import type { AuthStatus, CsrfToken, CurrentUser, LogoutResult } from "@/types/auth";

/** Where the browser goes to begin Google sign-in. */
export const LOGIN_PATH = "/auth/google/login";

/**
 * Return the signed-in user.
 *
 * Throws an `ApiError` with `kind: "unauthorized"` when there is no session,
 * which is the normal signal for an anonymous visitor rather than a failure.
 */
export async function fetchCurrentUser(): Promise<CurrentUser> {
  const response = await get<ApiEnvelope<CurrentUser>>("/auth/me");
  return response.data;
}

/** Report whether Google sign-in is configured on this deployment. */
export async function fetchAuthStatus(): Promise<AuthStatus> {
  const response = await get<ApiEnvelope<AuthStatus>>("/auth/status");
  return response.data;
}

/**
 * Obtain a CSRF token, which is also set as a readable cookie.
 *
 * Called before a state-changing request rather than kept in long-lived state:
 * the token's lifetime matches the session, and fetching one costs a single
 * round trip on the rare occasions it is needed.
 */
export async function fetchCsrfToken(): Promise<string> {
  const response = await get<ApiEnvelope<CsrfToken>>("/auth/csrf");
  return response.data.csrf_token;
}

/**
 * End the session.
 *
 * The backend revokes the token server-side and clears both cookies. The CSRF
 * token is fetched first because logout is a POST, and every state-changing
 * request must carry one.
 */
export async function logout(): Promise<LogoutResult> {
  const csrfToken = await fetchCsrfToken();
  const response = await post<ApiEnvelope<LogoutResult>>("/auth/logout", undefined, {
    headers: { "X-CSRF-Token": csrfToken },
  });
  return response.data;
}

/**
 * Build the URL that starts Google sign-in.
 *
 * `next` is sent as a path and validated server-side against an allow-list, so
 * a caller cannot use it to redirect elsewhere after login (spec section 21).
 * Passing an absolute URL here is harmless -- the backend discards it.
 */
export function buildLoginUrl(next?: string): string {
  const base = `${process.env.NEXT_PUBLIC_API_BASE_URL}${LOGIN_PATH}`;
  if (!next || !next.startsWith("/")) {
    return base;
  }
  return `${base}?next=${encodeURIComponent(next)}`;
}
