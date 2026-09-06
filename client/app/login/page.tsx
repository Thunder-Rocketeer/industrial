"use client";

import { Icon } from "@/components/ui/Icon";
import { AuthLoadingState } from "@/components/layout/RequireAuth";
import { buildLoginUrl, fetchAuthStatus } from "@/lib/api/auth";
import { useAuth } from "@/providers/auth-provider";
import { STALE_TIME } from "@/lib/constants/cache";
import { useQuery } from "@tanstack/react-query";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect } from "react";

/**
 * Messages for the reason codes the backend appends after a failed sign-in.
 *
 * The backend deliberately sends a short opaque code rather than a message, so
 * it never reveals which check refused a caller. The copy lives here, where it
 * can be written for a person.
 */
const FAILURE_MESSAGES: Record<string, string> = {
  oauth_failed: "Sign-in with Google did not complete. Please try again.",
  identity_invalid:
    "Google did not return a verified email address for that account. Try an account with a confirmed email.",
  not_permitted: "That account is not permitted to sign in to this application.",
  not_configured: "Sign-in is not configured on this deployment.",
  auth_failed: "Sign-in was not successful. Please try again.",
};

function LoginContent() {
  const { state } = useAuth();
  const router = useRouter();
  const searchParams = useSearchParams();

  const next = searchParams.get("next");
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
      router.replace(next && next.startsWith("/") ? next : "/");
    }
  }, [state, next, router]);

  if (state === "loading") {
    return <AuthLoadingState />;
  }

  const configured = status.data?.google_configured ?? false;
  const failureMessage = reason ? (FAILURE_MESSAGES[reason] ?? FAILURE_MESSAGES.auth_failed) : null;

  return (
    <div className="flex flex-1 items-center justify-center bg-zinc-50 px-6 py-16 dark:bg-zinc-950">
      <main id="main-content" className="w-full max-w-sm">
        <div className="rounded-lg border border-zinc-200 bg-white p-8 shadow-sm dark:border-zinc-800 dark:bg-zinc-900">
          <h1 className="text-xl font-semibold tracking-tight text-zinc-900 dark:text-zinc-50">
            Sign in
          </h1>
          <p className="mt-2 text-sm leading-relaxed text-zinc-600 dark:text-zinc-400">
            Automobile Component Factory operations dashboard.
          </p>

          {failureMessage ? (
            // `role="alert"` so a screen reader announces the failure rather
            // than leaving the user to discover it. Text, not colour alone.
            <div
              role="alert"
              className="mt-6 rounded border border-red-300 bg-red-50 p-3 text-sm text-red-900 dark:border-red-900 dark:bg-red-950 dark:text-red-200"
            >
              <span className="font-medium">Sign-in failed. </span>
              {failureMessage}
            </div>
          ) : null}

          {status.isPending ? (
            <div className="mt-6 h-11 w-full animate-pulse rounded bg-zinc-200 dark:bg-zinc-800" />
          ) : configured ? (
            // A plain link, not a fetch. Sign-in is a top-level navigation to
            // Google; an XHR could not follow the redirect chain, and the
            // browser must own the address bar for the user to see the real
            // Google domain before typing a password.
            <a
              href={buildLoginUrl(next ?? undefined)}
              className="mt-6 flex w-full items-center justify-center gap-3 rounded border border-zinc-300 bg-white px-4 py-2.5 text-sm font-medium text-zinc-900 transition hover:bg-zinc-50 focus:outline focus:outline-2 focus:outline-offset-2 focus:outline-blue-600 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-50 dark:hover:bg-zinc-800"
            >
              <Icon name="logos:google-icon" size={18} />
              Continue with Google
            </a>
          ) : (
            <div
              role="status"
              className="mt-6 rounded border border-amber-300 bg-amber-50 p-3 text-sm text-amber-900 dark:border-amber-900 dark:bg-amber-950 dark:text-amber-200"
            >
              <span className="font-medium">Sign-in is unavailable. </span>
              Google credentials are not configured on this deployment. See{" "}
              <code className="font-mono text-xs">docs/authentication.md</code>.
            </div>
          )}

          <p className="mt-6 text-xs leading-relaxed text-zinc-500 dark:text-zinc-500">
            Your session is held in a secure, HTTP-only cookie. No access token is stored in the
            browser.
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
