"use client";

/**
 * `/login` (spec sections 30 and 31).
 *
 * Restyled in Phase 6 onto the design system. The authentication mechanism is
 * unchanged from Phase 4 and deliberately so: sign-in is still a top-level
 * navigation to Google, the session is still an HttpOnly cookie, and nothing
 * here reads or stores a token.
 *
 * Two things this page is careful about:
 *
 *  - **It explains a refusal without describing the check.** The backend sends
 *    a short opaque reason code precisely so it never reveals which control
 *    rejected a caller; the copy below turns that into something a person can
 *    act on, without disclosing whether the account was unknown, inactive, or
 *    outside the permitted domain (spec section 30).
 *
 *  - **`next` is validated before use.** Only a same-site path is accepted, so
 *    a crafted `?next=https://evil.example` cannot turn the sign-in flow into an
 *    open redirect (spec section 36).
 */
import { useQuery } from "@tanstack/react-query";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect } from "react";

import { AuthLoadingState } from "@/components/layout/RequireAuth";
import { Icon } from "@/components/ui/Icon";
import { Skeleton } from "@/components/ui/States";
import { buildLoginUrl, fetchAuthStatus } from "@/lib/api/auth";
import { STALE_TIME } from "@/lib/constants/cache";
import { useAuth } from "@/providers/auth-provider";

/**
 * Copy for the reason codes the backend appends after a failed sign-in.
 *
 * Written for a person, and deliberately vague about the mechanism: none of
 * these says which check failed, only what the user can do next.
 */
const FAILURE_MESSAGES: Record<string, string> = {
  oauth_failed: "Sign-in with Google did not complete. Please try again.",
  identity_invalid:
    "Google did not return a verified email address for that account. Try an account with a confirmed email address.",
  not_permitted:
    "That account is not permitted to use this application. If you believe it should be, contact your factory systems administrator.",
  not_configured: "Sign-in is not configured on this deployment.",
  auth_failed: "Your session has ended. Please sign in again.",
};

/**
 * Accept a redirect target only if it is a same-site path.
 *
 * A value starting with `//` is protocol-relative and navigates off-site, so a
 * leading slash alone is not sufficient.
 */
function safeNextPath(value: string | null): string | undefined {
  if (!value || !value.startsWith("/") || value.startsWith("//")) {
    return undefined;
  }
  return value;
}

function LoginContent() {
  const { state } = useAuth();
  const router = useRouter();
  const searchParams = useSearchParams();

  const next = safeNextPath(searchParams.get("next"));
  const reason = searchParams.get("reason");

  const status = useQuery({
    queryKey: ["auth", "status"],
    queryFn: fetchAuthStatus,
    staleTime: STALE_TIME.reference,
    retry: false,
  });

  // An already-signed-in user has no business on the login page.
  useEffect(() => {
    if (state === "authenticated") {
      router.replace(next ?? "/dashboard");
    }
  }, [state, next, router]);

  if (state === "loading") {
    return <AuthLoadingState />;
  }

  const configured = status.data?.google_configured ?? false;
  const failureMessage = reason ? (FAILURE_MESSAGES[reason] ?? FAILURE_MESSAGES.auth_failed) : null;
  // The session-expiry watcher sends this code; it is an interruption, not a
  // failure, and reads better as such.
  const isSessionExpiry = reason === "auth_failed";

  return (
    <div className="bg-background flex min-h-dvh flex-1 items-center justify-center px-4 py-12">
      <main id="main-content" className="w-full max-w-sm">
        <div className="mb-6 flex items-center gap-2.5">
          <span
            className="bg-accent text-accent-fg flex size-9 shrink-0 items-center justify-center rounded"
            aria-hidden="true"
          >
            <Icon name="mdi:factory" size={21} />
          </span>
          <div className="min-w-0">
            <p className="text-foreground text-sm leading-tight font-semibold">
              Industrial Factory Dashboard
            </p>
            <p className="text-subtle text-xs leading-tight">Automobile component manufacturing</p>
          </div>
        </div>

        <div className="border-border-base bg-surface rounded-md border p-6">
          <h1 className="text-foreground text-lg font-semibold tracking-tight">Sign in</h1>
          <p className="text-muted mt-1.5 text-sm leading-relaxed">
            Production, quality, inventory and machine monitoring for the factory floor.
          </p>

          {failureMessage && (
            <div
              // `role="alert"` so the message is announced rather than left for
              // the user to discover. Text, never colour alone (WCAG 1.4.1).
              role="alert"
              className={
                isSessionExpiry
                  ? "border-warn/30 bg-warn-soft text-warn-fg mt-5 rounded border p-3 text-sm"
                  : "border-critical/30 bg-critical-soft text-critical-fg mt-5 rounded border p-3 text-sm"
              }
            >
              <span className="font-medium">
                {isSessionExpiry ? "Session ended. " : "Sign-in failed. "}
              </span>
              {failureMessage}
            </div>
          )}

          {status.isPending ? (
            <Skeleton className="mt-5 h-11 w-full" />
          ) : configured ? (
            /*
             * A plain link, not a fetch.
             *
             * Sign-in is a top-level navigation to Google. An XHR could not
             * follow the redirect chain, and more importantly the browser must
             * own the address bar so the user sees the real Google domain
             * before typing a password.
             */
            <a
              href={buildLoginUrl(next)}
              className="border-border-strong bg-surface text-foreground hover:bg-surface-sunken mt-5 flex w-full items-center justify-center gap-3 rounded border px-4 py-2.5 text-sm font-medium transition-colors"
            >
              <Icon name="logos:google-icon" size={18} />
              Continue with Google
            </a>
          ) : (
            <div
              role="status"
              className="border-warn/30 bg-warn-soft text-warn-fg mt-5 rounded border p-3 text-sm"
            >
              <span className="font-medium">Sign-in is unavailable. </span>
              Google credentials are not configured on this deployment. See{" "}
              <code className="font-mono text-xs">docs/authentication.md</code>.
            </div>
          )}

          <p className="text-subtle mt-5 text-xs leading-relaxed">
            Access is restricted to authorized factory accounts. Your session is held in a secure,
            HTTP-only cookie; no access token is stored in the browser.
          </p>
        </div>
      </main>
    </div>
  );
}

/**
 * `useSearchParams` requires a Suspense boundary in the App Router, because it
 * opts the subtree into client-side rendering. Without it the build fails.
 */
export default function LoginPage() {
  return (
    <Suspense fallback={<AuthLoadingState />}>
      <LoginContent />
    </Suspense>
  );
}
