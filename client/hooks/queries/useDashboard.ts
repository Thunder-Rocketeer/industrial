"use client";

/**
 * Dashboard query hooks.
 *
 * The KPI values, OEE terms and alert counts arrive already computed. Spec
 * section 7 is explicit: "Do not calculate these KPIs again in React." These
 * hooks fetch and cache; they do not derive.
 */
import { useQuery } from "@tanstack/react-query";

import { fetchDashboardSummary, fetchDashboardTrends } from "@/lib/api/dashboard";
import { DASHBOARD_REFETCH_INTERVAL, GC_TIME, STALE_TIME } from "@/lib/constants/cache";
import { queryKeys } from "@/lib/query/query-keys";
import { type QueryState, toQueryState } from "@/lib/query/query-state";
import type { DashboardSummary, DashboardTrends, TrendFilters } from "@/types/dashboard";

/**
 * The executive dashboard summary.
 *
 * Polls every 30 seconds (spec section 33). This is the only polling query in
 * the application -- historical analytics never poll, because their answer does
 * not change between requests and the traffic would be pure waste.
 *
 * `refetchIntervalInBackground` is left false so a tab left open overnight
 * stops polling when hidden, which spec section 33 asks for and which spares
 * both the browser and the backend rate limit.
 */
export function useDashboardSummary(
  options: { enabled?: boolean } = {},
): QueryState<DashboardSummary> {
  const query = useQuery({
    queryKey: queryKeys.dashboard.summary(),
    queryFn: fetchDashboardSummary,
    staleTime: STALE_TIME.realtime,
    gcTime: GC_TIME.default,
    refetchInterval: DASHBOARD_REFETCH_INTERVAL,
    refetchIntervalInBackground: false,
    enabled: options.enabled ?? true,
  });

  // A summary is never "empty": zeroed KPIs are a valid answer for a quiet
  // factory. `has_data` on the nested summaries is what distinguishes that from
  // no matching records, and a panel reads it directly.
  return toQueryState(query, () => false);
}

/**
 * Chart series for the dashboard.
 *
 * Does not poll. The trend covers 30 days by default, so a 30-second refresh
 * would redraw the same chart with one more hour of data.
 */
export function useDashboardTrends(
  filters: TrendFilters = {},
  options: { enabled?: boolean } = {},
): QueryState<DashboardTrends> {
  const query = useQuery({
    queryKey: queryKeys.dashboard.trends(filters),
    queryFn: () => fetchDashboardTrends(filters),
    staleTime: STALE_TIME.trend,
    gcTime: GC_TIME.default,
    enabled: options.enabled ?? true,
  });

  return toQueryState(query, (data) => !data.has_data);
}
