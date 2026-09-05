/**
 * TanStack Query client configuration.
 *
 * Spec section 16: query keys are structured, stale times reflect data
 * volatility, refetches are deliberate, and retry policy is conservative rather
 * than blind.
 */
import { QueryClient, keepPreviousData, type QueryClientConfig } from "@tanstack/react-query";

import { ApiError } from "@/lib/api/errors";
import { GC_TIME, STALE_TIME } from "@/lib/constants/cache";

/** Maximum automatic retries for a failed query. */
const MAX_QUERY_RETRIES = 2;

/**
 * Retry only failures that a retry could plausibly fix.
 *
 * Retrying a 401/403/404/422 is wasted work: the outcome is deterministic. A
 * 429 is not retried automatically either, since doing so would work against
 * the backend rate limiter (spec section 60).
 */
function shouldRetry(failureCount: number, error: unknown): boolean {
  if (failureCount >= MAX_QUERY_RETRIES) return false;
  if (error instanceof ApiError) return error.isRetryable;
  return false;
}

/** Exponential backoff, capped so the UI never appears to hang. */
function retryDelay(attemptIndex: number): number {
  return Math.min(1000 * 2 ** attemptIndex, 10_000);
}

export const queryClientConfig: QueryClientConfig = {
  defaultOptions: {
    queries: {
      staleTime: STALE_TIME.trend,
      gcTime: GC_TIME.default,
      retry: shouldRetry,
      retryDelay,
      // Spec section 33: avoid aggressive polling. Focus refetches are enabled
      // so a returning user sees current data, but interval polling is opt-in
      // per query rather than global.
      refetchOnWindowFocus: true,
      refetchOnReconnect: true,
      refetchOnMount: false,
      // Spec section 37: keep previously loaded data visible during a transient
      // refetch failure instead of flashing an empty state.
      placeholderData: keepPreviousData,
      throwOnError: false,
    },
    mutations: {
      retry: false,
      throwOnError: false,
    },
  },
};

/**
 * Creates a QueryClient.
 *
 * A factory rather than a module-level singleton: on the server every request
 * must get its own cache so that one user's data can never leak into another's
 * response. The browser-side singleton is managed in the query provider.
 */
export function createQueryClient(): QueryClient {
  return new QueryClient(queryClientConfig);
}
