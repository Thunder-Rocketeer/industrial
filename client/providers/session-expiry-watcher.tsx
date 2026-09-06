"use client";

import { useQueryClient } from "@tanstack/react-query";
import { usePathname, useRouter } from "next/navigation";
import { useEffect } from "react";

import { onSessionExpired } from "@/lib/api/client";
import { queryKeys } from "@/lib/query/query-keys";

/**
 * Reacts to a session ending mid-use (spec section 27).
 *
 * The Axios layer detects a 401 on any request and notifies once; this
 * component turns that into the three things that must happen: drop the cached
 * user, clear data fetched as them, and send them to sign in again.
 *
 * Renders nothing. It exists as a component only so it can use the router and
 * the query client, which are React-scoped.
 *
 * Two loops are deliberately avoided. The Axios layer suppresses repeat
 * notifications within a short window, so a dashboard firing several requests
 * at once produces one redirect rather than six. And the redirect is skipped
 * when the user is already on the login page, which would otherwise be a
 * navigation to the page they are already on, every time the session probe
 * returns 401.
 */
export function SessionExpiryWatcher() {
  const queryClient = useQueryClient();
  const router = useRouter();
  const pathname = usePathname();

  useEffect(() => {
    return onSessionExpired(() => {
      // Mark the session unknown so the auth provider stops reporting a user.
      queryClient.setQueryData(queryKeys.auth.currentUser(), undefined);
      // Remove everything fetched as the previous user, so nothing of theirs
      // can be shown to whoever signs in next.
      queryClient.clear();

      if (pathname === "/login") {
        return;
      }
      const next = `${pathname}${window.location.search}`;
      router.replace(`/login?next=${encodeURIComponent(next)}&reason=auth_failed`);
    });
  }, [queryClient, router, pathname]);

  return null;
}
