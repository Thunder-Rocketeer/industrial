"use client";

/**
 * Whether the backend is reachable, application-wide (spec section 29).
 *
 * When the API is down, every panel fails at once. Without something watching
 * globally, the user sees eight identical "cannot reach the server" boxes and
 * has to guess whether the dashboard is broken or the service is. This hook
 * gives the shell one place to say it once.
 *
 * The distinction it draws is deliberate, and comes from `isBackendUnavailable`:
 * a network failure, timeout or 5xx means the *service* is unavailable, while a
 * 403 or 422 means the service answered and refused this particular request.
 * Only the first kind belongs in a global banner; the second belongs inline on
 * the panel it concerns.
 *
 * The hook observes the existing query cache. It issues no health-check request
 * of its own -- polling `/health` on a timer to discover what the failing
 * queries already know would add traffic during exactly the outage where the
 * service is least able to absorb it.
 */
import { notifyManager, useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useState } from "react";

import { isApiError } from "@/lib/api/errors";
import { isBackendUnavailable } from "@/lib/query/query-state";

export interface BackendStatus {
  /** At least one query is failing because the service cannot be reached. */
  isUnavailable: boolean;
  /** How many queries are currently failing that way. */
  failingQueryCount: number;
  /**
   * When any query last returned data, as an epoch milliseconds value, or null
   * if none ever has.
   *
   * Spec section 29 asks that last-known data stay visible during an outage.
   * TanStack Query keeps it in the cache already; this is what lets the UI say
   * how old it is, so nobody reads a stale number as current.
   */
  lastSuccessAt: number | null;
  /** Retry every failing query. Wired to the banner's retry button. */
  retry: () => void;
}

interface CacheSnapshot {
  failingQueryCount: number;
  lastSuccessAt: number | null;
}

const EMPTY: CacheSnapshot = { failingQueryCount: 0, lastSuccessAt: null };

export function useBackendStatus(): BackendStatus {
  const queryClient = useQueryClient();
  const [snapshot, setSnapshot] = useState<CacheSnapshot>(EMPTY);

  useEffect(() => {
    const cache = queryClient.getQueryCache();

    const read = () => {
      let failingQueryCount = 0;
      let lastSuccessAt: number | null = null;

      for (const query of cache.getAll()) {
        const { status, error, dataUpdatedAt } = query.state;

        if (status === "error" && isApiError(error) && isBackendUnavailable(error)) {
          failingQueryCount += 1;
        }
        if (dataUpdatedAt > 0 && (lastSuccessAt === null || dataUpdatedAt > lastSuccessAt)) {
          lastSuccessAt = dataUpdatedAt;
        }
      }

      setSnapshot((current) =>
        current.failingQueryCount === failingQueryCount && current.lastSuccessAt === lastSuccessAt
          ? // Same values: return the same object so React skips the re-render.
            // Without this the cache's own subscription would re-render the
            // whole shell on every background refetch.
            current
          : { failingQueryCount, lastSuccessAt },
      );
    };

    read();
    // The cache notifies subscribers synchronously, and a query is added to
    // it while the component that owns it is rendering. Updating state right
    // then is a state update during another component's render, which React
    // rejects. Scheduling the read through the query library's own notifier
    // moves it out of the render phase and coalesces a burst of cache events
    // into one pass.
    return cache.subscribe(() => notifyManager.schedule(read));
  }, [queryClient]);

  const retry = useCallback(() => {
    void queryClient.refetchQueries({
      // Only the queries that failed. Refetching everything would re-request
      // panels that are fine, and on a recovering backend that is a burst of
      // traffic at the worst moment.
      predicate: (query) => query.state.status === "error",
    });
  }, [queryClient]);

  return {
    isUnavailable: snapshot.failingQueryCount > 0,
    failingQueryCount: snapshot.failingQueryCount,
    lastSuccessAt: snapshot.lastSuccessAt,
    retry,
  };
}
