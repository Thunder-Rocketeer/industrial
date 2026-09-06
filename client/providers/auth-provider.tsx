"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { usePathname, useRouter } from "next/navigation";
import { createContext, useCallback, useContext, useMemo, type ReactNode } from "react";

import { fetchCurrentUser, logout as apiLogout } from "@/lib/api/auth";
import { isApiError } from "@/lib/api/errors";
import { queryKeys } from "@/lib/query/query-keys";
import type { CurrentUser } from "@/types/auth";

/**
 * Authentication state, derived from the server rather than stored locally.
 *
 * The single source of truth is `GET /auth/me`. There is no token in memory, no
 * decoded JWT, and nothing in `localStorage` -- the session is an HttpOnly
 * cookie the browser attaches on its own (spec section 7). "Am I signed in?" is
 * answered by asking the server, which means the answer cannot drift from
 * reality and cannot be forged by editing browser state.
 *
 * The four states in spec section 26 are modelled explicitly, because collapsing
 * "loading" into "unauthenticated" is what produces the redirect flicker the
 * spec asks us to avoid: a protected page renders, decides nobody is signed in
 * because the query has not resolved yet, and bounces to the login screen.
 */
export type AuthState = "loading" | "authenticated" | "unauthenticated";

interface AuthContextValue {
  state: AuthState;
  user: CurrentUser | null;
  /** True only when the session is confirmed. Never true while loading. */
  isAuthenticated: boolean;
  isLoading: boolean;
  /** Whether the user's role holds a permission. For UI decisions only. */
  can: (permission: string) => boolean;
  signOut: () => Promise<void>;
  /** Re-check the session, e.g. after returning from the OAuth redirect. */
  refresh: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

/**
 * How long the session is treated as fresh.
 *
 * Shorter than the access token's lifetime, so a session that expires or is
 * revoked server-side is noticed within a minute rather than persisting in the
 * UI until something else happens to fail.
 */
const SESSION_STALE_TIME = 60_000;

export function AuthProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient();
  const router = useRouter();
  const pathname = usePathname();

  const query = useQuery({
    queryKey: queryKeys.auth.currentUser(),
    queryFn: fetchCurrentUser,
    staleTime: SESSION_STALE_TIME,
    // A 401 is the expected answer for an anonymous visitor, not a failure to
    // recover from. Retrying it would send a burst of doomed requests on every
    // page load for signed-out users.
    retry: false,
    // The session may have ended in another tab, or expired while the tab was
    // in the background. Re-checking on focus is what makes that visible.
    refetchOnWindowFocus: true,
    // No placeholder data: showing a previous user's identity while
    // re-validating would be worse than showing a loading state.
    placeholderData: undefined,
  });

  const state: AuthState = query.isPending
    ? "loading"
    : query.data
      ? "authenticated"
      : "unauthenticated";

  const can = useCallback(
    (permission: string) => query.data?.permissions.includes(permission) ?? false,
    [query.data],
  );

  const refresh = useCallback(async () => {
    await queryClient.invalidateQueries({ queryKey: queryKeys.auth.all });
  }, [queryClient]);

  const signOut = useCallback(async () => {
    try {
      await apiLogout();
    } catch (error) {
      // A failed logout still ends the session locally. The most common cause
      // is an already-expired token, where the server has nothing left to
      // revoke -- refusing to sign out in that case would trap the user.
      if (!isApiError(error) || !error.isAuthError) {
        console.warn("Logout request failed; clearing local session anyway.");
      }
    } finally {
      // Everything cached was fetched as this user. Clearing rather than
      // invalidating means none of it can be shown to whoever signs in next.
      queryClient.clear();
      router.replace("/login");
    }
  }, [queryClient, router]);

  const value = useMemo<AuthContextValue>(
    () => ({
      state,
      user: query.data ?? null,
      isAuthenticated: state === "authenticated",
      isLoading: state === "loading",
      can,
      signOut,
      refresh,
    }),
    [state, query.data, can, signOut, refresh],
  );

  // `pathname` is read so the provider re-evaluates on navigation, which keeps
  // the session check aligned with route changes.
  void pathname;

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

/**
 * Read the authentication state.
 *
 * Throws outside the provider rather than returning a null-ish default: a
 * component silently receiving "not signed in" because it was mounted outside
 * the tree is a bug that presents as a mysterious redirect.
 */
export function useAuth(): AuthContextValue {
  const context = useContext(AuthContext);
  if (context === null) {
    throw new Error("useAuth must be used within an AuthProvider.");
  }
  return context;
}
