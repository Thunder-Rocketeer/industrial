"use client";

/**
 * Alert query hooks.
 */
import { keepPreviousData, useQuery } from "@tanstack/react-query";

import { fetchActiveAlerts, fetchAlerts, fetchAlertSummary } from "@/lib/api/alerts";
import { GC_TIME, STALE_TIME } from "@/lib/constants/cache";
import { queryKeys } from "@/lib/query/query-keys";
import { type QueryState, toQueryState } from "@/lib/query/query-state";
import type { Alert, AlertFilters, AlertSummary } from "@/types/alerts";
import type { PaginatedResponse } from "@/types/api";

/** One page of alerts, most severe and most recent first. */
export function useAlerts(
  filters: AlertFilters = {},
  options: { enabled?: boolean } = {},
): QueryState<PaginatedResponse<Alert>> {
  const query = useQuery({
    queryKey: queryKeys.alerts.list(filters),
    queryFn: () => fetchAlerts(filters),
    staleTime: STALE_TIME.realtime,
    gcTime: GC_TIME.default,
    placeholderData: keepPreviousData,
    enabled: options.enabled ?? true,
  });

  return toQueryState(query, (data) => data.data.length === 0);
}

/**
 * Open alerts, for the dashboard panel.
 *
 * Realtime tier: an alert the operator has not seen is the one piece of data
 * where being a minute late has an operational cost.
 */
export function useActiveAlerts(
  limit?: number,
  options: { enabled?: boolean } = {},
): QueryState<Alert[]> {
  const query = useQuery({
    queryKey: queryKeys.alerts.active(limit),
    queryFn: () => fetchActiveAlerts(limit),
    staleTime: STALE_TIME.realtime,
    gcTime: GC_TIME.default,
    enabled: options.enabled ?? true,
  });

  // An empty list means nothing is wrong, which is a state worth rendering
  // deliberately rather than as a blank panel.
  return toQueryState(query);
}

/**
 * Counts of open alerts by severity.
 *
 * Cached separately from the list so a badge showing the critical count does
 * not have to fetch, hold and re-render every alert to display one number
 * (spec section 13).
 */
export function useAlertSummary(options: { enabled?: boolean } = {}): QueryState<AlertSummary> {
  const query = useQuery({
    queryKey: queryKeys.alerts.summary(),
    queryFn: fetchAlertSummary,
    staleTime: STALE_TIME.realtime,
    gcTime: GC_TIME.default,
    enabled: options.enabled ?? true,
  });

  return toQueryState(query, () => false);
}
