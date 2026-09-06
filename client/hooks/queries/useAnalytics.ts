"use client";

/**
 * Analytics query hooks.
 *
 * Every value is the backend's. Spec section 12: "Use backend-calculated
 * analytics. Do not duplicate OEE calculations."
 *
 * These use the `historical` stale tier and never poll. Analytics answer
 * questions about a period that has already happened, so the answer does not
 * change between requests -- and they are the most expensive queries in the
 * API, carrying the strictest rate limit.
 */
import { keepPreviousData, useQuery } from "@tanstack/react-query";

import {
  fetchDefectAnalytics,
  fetchDowntimeByMachine,
  fetchEfficiencyTrend,
  fetchOee,
  fetchOeeByMachine,
  fetchOeeTrend,
  fetchProductionEfficiency,
} from "@/lib/api/analytics";
import { GC_TIME, STALE_TIME } from "@/lib/constants/cache";
import { queryKeys } from "@/lib/query/query-keys";
import { type QueryState, toQueryState } from "@/lib/query/query-state";
import type {
  AnalyticsFilters,
  DefectAnalytics,
  DowntimeByMachine,
  EfficiencySummary,
  EfficiencyTrendPoint,
  OEEByMachine,
  OEESummary,
  OEETrendPoint,
} from "@/types/analytics";

/** OEE for the filtered period, with its three terms. */
export function useOee(
  filters: AnalyticsFilters = {},
  options: { enabled?: boolean } = {},
): QueryState<OEESummary> {
  const query = useQuery({
    queryKey: queryKeys.analytics.oee(filters),
    queryFn: () => fetchOee(filters),
    staleTime: STALE_TIME.historical,
    gcTime: GC_TIME.default,
    placeholderData: keepPreviousData,
    enabled: options.enabled ?? true,
  });

  return toQueryState(query, (data) => !data.has_data);
}

/** Daily OEE for the trend chart. */
export function useOeeTrend(
  filters: AnalyticsFilters = {},
  options: { enabled?: boolean } = {},
): QueryState<OEETrendPoint[]> {
  const query = useQuery({
    queryKey: queryKeys.analytics.oeeTrend(filters),
    queryFn: () => fetchOeeTrend(filters),
    staleTime: STALE_TIME.historical,
    gcTime: GC_TIME.default,
    placeholderData: keepPreviousData,
    enabled: options.enabled ?? true,
  });

  return toQueryState(query);
}

/** OEE per machine, lowest first. */
export function useOeeByMachine(
  filters: AnalyticsFilters = {},
  options: { enabled?: boolean } = {},
): QueryState<OEEByMachine[]> {
  const query = useQuery({
    queryKey: queryKeys.analytics.oeeByMachine(filters),
    queryFn: () => fetchOeeByMachine(filters),
    staleTime: STALE_TIME.historical,
    gcTime: GC_TIME.default,
    placeholderData: keepPreviousData,
    enabled: options.enabled ?? true,
  });

  return toQueryState(query);
}

/** Production efficiency against plan and target. */
export function useProductionEfficiency(
  filters: AnalyticsFilters = {},
  options: { enabled?: boolean } = {},
): QueryState<EfficiencySummary> {
  const query = useQuery({
    queryKey: queryKeys.analytics.efficiency(filters),
    queryFn: () => fetchProductionEfficiency(filters),
    staleTime: STALE_TIME.historical,
    gcTime: GC_TIME.default,
    placeholderData: keepPreviousData,
    enabled: options.enabled ?? true,
  });

  return toQueryState(query, (data) => !data.has_data);
}

/** Daily efficiency and target achievement. */
export function useEfficiencyTrend(
  filters: AnalyticsFilters = {},
  options: { enabled?: boolean } = {},
): QueryState<EfficiencyTrendPoint[]> {
  const query = useQuery({
    queryKey: queryKeys.analytics.efficiencyTrend(filters),
    queryFn: () => fetchEfficiencyTrend(filters),
    staleTime: STALE_TIME.historical,
    gcTime: GC_TIME.default,
    placeholderData: keepPreviousData,
    enabled: options.enabled ?? true,
  });

  return toQueryState(query);
}

/** Downtime per machine, worst first. */
export function useDowntimeByMachine(
  filters: AnalyticsFilters = {},
  options: { enabled?: boolean } = {},
): QueryState<DowntimeByMachine[]> {
  const query = useQuery({
    queryKey: queryKeys.analytics.downtime(filters),
    queryFn: () => fetchDowntimeByMachine(filters),
    staleTime: STALE_TIME.historical,
    gcTime: GC_TIME.default,
    placeholderData: keepPreviousData,
    enabled: options.enabled ?? true,
  });

  return toQueryState(query);
}

/** Complete defect analysis in one response. */
export function useDefectAnalytics(
  filters: AnalyticsFilters = {},
  options: { enabled?: boolean } = {},
): QueryState<DefectAnalytics> {
  const query = useQuery({
    queryKey: queryKeys.analytics.defects(filters),
    queryFn: () => fetchDefectAnalytics(filters),
    staleTime: STALE_TIME.historical,
    gcTime: GC_TIME.default,
    placeholderData: keepPreviousData,
    enabled: options.enabled ?? true,
  });

  return toQueryState(query, (data) => !data.has_data);
}
