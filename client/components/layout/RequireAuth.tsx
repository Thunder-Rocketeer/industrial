"use client";

import { useRouter } from "next/navigation";
import { useEffect, type ReactNode } from "react";

import { useAuth } from "@/providers/auth-provider";

/**
 * Renders its children only for a signed-in user.
 *
 * **This is UX, not security.** Everything it guards is fetched from an API
 * that enforces the same rules server-side, so a user who defeats this sees an
 * empty shell and a series of 401s rather than any data (spec section 25).
 *
 * The point is avoiding flicker (spec section 26). The three states are handled
 * separately, and crucially "loading" is not treated as "unauthenticated" --
 * that conflation is what makes a protected page render, decide nobody is
 * signed in because the session check has not resolved, and bounce to login
 * before bouncing back.
 */
export function RequireAuth({
  children,
  fallback,
}: {
  children: ReactNode;
  /** Shown while the session is being checked. A skeleton, not a spinner. */
  fallback?: ReactNode;
}) {
  const { state } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (state !== "unauthenticated") {
      return;
    }
    // Remember where they were headed, so sign-in returns them there. Sent as a
    // path; the backend validates it against an allow-list, so it cannot become
    // an open redirect (spec section 21).
    const next = `${window.location.pathname}${window.location.search}`;
    const target = next === "/login" ? "/login" : `/login?next=${encodeURIComponent(next)}`;
    // `replace`, not `push`: the protected URL must not stay in history, or the
    // back button returns to a page that immediately redirects again.
    router.replace(target);
  }, [state, router]);

  if (state === "loading") {
    return <>{fallback ?? <AuthLoadingState />}</>;
  }

  if (state === "unauthenticated") {
    // The redirect is in flight. Render the loading state rather than the
    // children, so protected content is never briefly visible.
    return <>{fallback ?? <AuthLoadingState />}</>;
  }

  return <>{children}</>;
}

/**
 * Placeholder shown while the session is resolved.
 *
 * Announced to assistive technology with `aria-busy` and a live region, so a
 * screen reader user is told the page is working rather than met with silence.
 */
export function AuthLoadingState() {
  return (
    <div
      className="flex min-h-[60vh] items-center justify-center px-6"
      role="status"
      aria-busy="true"
      aria-live="polite"
    >
      <div className="w-full max-w-sm space-y-4">
        <div className="h-3 w-24 animate-pulse rounded bg-zinc-200 dark:bg-zinc-800" />
        <div className="h-10 w-full animate-pulse rounded bg-zinc-200 dark:bg-zinc-800" />
        <div className="h-10 w-2/3 animate-pulse rounded bg-zinc-200 dark:bg-zinc-800" />
        <span className="sr-only">Checking your sign-in status.</span>
      </div>
    </div>
  );
}

/**
 * Renders children only when the user's role holds a permission.
 *
 * Again UX only: it hides a control the backend would refuse anyway. Spec
 * section 12 is explicit that frontend route hiding is not authorization.
 */
export function RequirePermission({
  permission,
  children,
  fallback = null,
}: {
  permission: string;
  children: ReactNode;
  fallback?: ReactNode;
}) {
  const { can, state } = useAuth();

  if (state === "loading") {
    return <AuthLoadingState />;
  }
  return <>{can(permission) ? children : fallback}</>;
}
