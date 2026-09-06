import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

/**
 * Route protection at the edge (spec section 25).
 *
 * Next.js 16 renamed Middleware to **Proxy**: this file is `proxy.ts`, not
 * `middleware.ts`, and exports `proxy` rather than `middleware`. Copying an
 * older example would produce a file Next.js silently ignores, which is the
 * worst possible failure mode for a security control -- it looks present and
 * does nothing.
 *
 * WHAT THIS IS, AND IS NOT
 *
 * It is a UX optimisation. It spares a signed-out visitor a flash of empty
 * dashboard by redirecting before the page renders.
 *
 * It is **not** authorization. It checks only that a session cookie is
 * *present*, and cannot check that it is valid: the cookie is signed with a key
 * this process does not hold, and verifying it here would mean either shipping
 * the signing key to the edge or calling the API on every navigation.
 *
 * So the guarantee is deliberately weak, and the real one lives in the backend,
 * which validates the token, checks revocation, confirms the account is active
 * and enforces the permission -- on every single request. A user who forges a
 * cookie here gets past this file and then receives 401s from every endpoint
 * (spec section 25: "Keep frontend route protection as UX protection only.
 * Backend authorization remains authoritative").
 */

/** Must match `SESSION_COOKIE_NAME` on the backend. */
const SESSION_COOKIE = "acf_session";

/** Routes reachable without a session. */
const PUBLIC_PATHS = ["/login"];

export function proxy(request: NextRequest) {
  const { pathname, search } = request.nextUrl;

  if (PUBLIC_PATHS.some((path) => pathname === path || pathname.startsWith(`${path}/`))) {
    return NextResponse.next();
  }

  // Presence only. The cookie is HttpOnly and signed by the API, so its
  // contents are neither readable nor verifiable here.
  const hasSession = request.cookies.has(SESSION_COOKIE);
  if (hasSession) {
    return NextResponse.next();
  }

  const loginUrl = new URL("/login", request.url);
  // `next` is a path built from the request's own pathname, never from a query
  // parameter, so it cannot be used to smuggle an external destination. The
  // backend validates it again against its own allow-list.
  if (pathname !== "/") {
    loginUrl.searchParams.set("next", `${pathname}${search}`);
  }
  return NextResponse.redirect(loginUrl);
}

export const config = {
  /**
   * Everything except Next.js internals, static assets and the favicon.
   *
   * Running on `_next/static` would add a redirect check to every chunk
   * request, and running on an image would break it for a signed-out user on
   * the login page.
   */
  matcher: ["/((?!_next/static|_next/image|favicon.ico|.*\\.(?:svg|png|jpg|jpeg|gif|webp)$).*)"],
};
