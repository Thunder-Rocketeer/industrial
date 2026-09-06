/**
 * Authentication contract types.
 *
 * Mirrors `app/schemas/auth.py`. Deliberately has no field for a token: the
 * session lives in an HttpOnly cookie the browser attaches automatically, and
 * application JavaScript never sees it (spec section 7). A `token` field here
 * would be an invitation to start storing one.
 */

/** Role codes, matching the backend enum. */
export type RoleCode =
  | "ADMIN"
  | "FACTORY_MANAGER"
  | "PRODUCTION_SUPERVISOR"
  | "QUALITY_ENGINEER"
  | "INVENTORY_MANAGER"
  | "VIEWER";

/** The signed-in user, as returned by `GET /auth/me`. */
export interface CurrentUser {
  id: string;
  email: string;
  name: string;
  role: RoleCode;
  /** Human-readable role, e.g. "Factory Manager". Rendered as text. */
  role_label: string;
  avatar_url: string | null;
  is_active: boolean;
  last_login_at: string | null;
  /**
   * Permissions this role holds.
   *
   * For deciding what the UI offers -- never for authorization. The backend
   * enforces every check independently, and hiding a button is not a security
   * control (spec section 12).
   */
  permissions: string[];
}

/** Whether sign-in is available on this deployment. */
export interface AuthStatus {
  authentication_required: boolean;
  google_configured: boolean;
  login_url: string;
}

/** Outcome of a logout. */
export interface LogoutResult {
  logged_out: boolean;
  session_revoked: boolean;
}

/** A CSRF token for the double-submit check. */
export interface CsrfToken {
  csrf_token: string;
}

/** Reason codes the backend appends to the login page URL after a failure. */
export type LoginErrorReason =
  "oauth_failed" | "identity_invalid" | "not_permitted" | "not_configured" | "auth_failed";
