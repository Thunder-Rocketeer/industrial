"use client";

/**
 * Production query hooks.
 */
import { keepPreviousData, useQuery } from "@tanstack/react-query";

import {
  fetchProductionByDimension,
  fetchProductionRecords,
  fetchProductionSummary,
  fetchProductionTrend,
} from "@/lib/api/production";
import { GC_TIME, STALE_TIME } from "@/lib/constants/cache";
import { queryKeys } from "@/lib/query/query-keys";
import { type QueryState, toQueryState } from "@/lib/query/query-state";
import type { PaginatedResponse } from "@/types/api";
import type {
  ProductionByDimension,
  ProductionDimension,
  ProductionFilters,
  ProductionGroupFilters,
  ProductionListFilters,
  ProductionRecord,
  ProductionSummary,
  ProductionTrendPoint,
} from "@/types/production";

/**
 * One page of production records.
 *
 * `keepPreviousData` is what makes pagination feel like pagination rather than
 * a page reload: changing to page 2 keeps page 1 on screen until the new rows
 * arrive, so the table does not collapse to a skeleton and back (spec section
 * 20). `isRefreshing` is the signal to show a subtle indicator meanwhile.
 */
export function useProductionRecords(
  filters: ProductionListFilters = {},
  options: { enabled?: boolean } = {},
): QueryState<PaginatedResponse<ProductionRecord>> {
  const query = useQuery({
    queryKey: queryKeys.production.list(filters),
    queryFn: () => fetchProductionRecords(filters),
    staleTime: STALE_TIME.trend,
    gcTime: GC_TIME.default,
    placeholderData: keepPreviousData,
    enabled: options.enabled ?? true,
  });

  return toQueryState(query, (data) => data.data.length === 0);
}

/** Aggregate production for the filtered period. */
export function useProductionSummary(
  filters: ProductionFilters = {},
  options: { enabled?: boolean } = {},
): QueryState<ProductionSummary> {
  const query = useQuery({
    queryKey: queryKeys.production.summary(filters),
    queryFn: () => fetchProductionSummary(filters),
    staleTime: STALE_TIME.trend,
    gcTime: GC_TIME.default,
    placeholderData: keepPreviousData,
    enabled: options.enabled ?? true,
  });

  // The backend's own answer to "did anything match", rather than inspecting
  // whether the totals happen to be zero -- a real day of zero output is not an
  // empty result.
  return toQueryState(query, (data) => !data.has_data);
}

/** Daily production totals with the matching target. */
export function useProductionTrend(
  filters: ProductionFilters = {},
  options: { enabled?: boolean } = {},
): QueryState<ProductionTrendPoint[]> {
  const query = useQuery({
    queryKey: queryKeys.production.trend(filters),
    queryFn: () => fetchProductionTrend(filters),
    staleTime: STALE_TIME.trend,
    gcTime: GC_TIME.default,
    placeholderData: keepPreviousData,
    enabled: options.enabled ?? true,
  });

  return toQueryState(query);
}

/** Production totals grouped by machine, component, shift or line. */
export function useProductionByDimension(
  dimension: ProductionDimension,
  filters: ProductionGroupFilters = {},
  options: { enabled?: boolean } = {},
): QueryState<ProductionByDimension[]> {
  const query = useQuery({
    queryKey: queryKeys.production.byDimension(dimension, filters),
    queryFn: () => fetchProductionByDimension(dimension, filters),
    staleTime: STALE_TIME.trend,
    gcTime: GC_TIME.default,
    placeholderData: keepPreviousData,
    enabled: options.enabled ?? true,
  });

  return toQueryState(query);
}
