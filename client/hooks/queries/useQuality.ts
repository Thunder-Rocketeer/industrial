"use client";

/**
 * Quality query hooks.
 */
import { keepPreviousData, useQuery } from "@tanstack/react-query";

import {
  fetchDefectBreakdown,
  fetchDefectTrend,
  fetchQualityByDimension,
  fetchQualityRecords,
  fetchQualitySummary,
} from "@/lib/api/quality";
import { GC_TIME, STALE_TIME } from "@/lib/constants/cache";
import { queryKeys } from "@/lib/query/query-keys";
import { type QueryState, toQueryState } from "@/lib/query/query-state";
import type { PaginatedResponse } from "@/types/api";
import type {
  DefectBreakdownFilters,
  DefectSummary,
  DefectTrendPoint,
  QualityByDimension,
  QualityDimension,
  QualityFilters,
  QualityListFilters,
  QualityRecord,
  QualitySummary,
} from "@/types/quality";

/** One page of inspection lines. */
export function useQualityRecords(
  filters: QualityListFilters = {},
  options: { enabled?: boolean } = {},
): QueryState<PaginatedResponse<QualityRecord>> {
  const query = useQuery({
    queryKey: queryKeys.quality.list(filters),
    queryFn: () => fetchQualityRecords(filters),
    staleTime: STALE_TIME.trend,
    gcTime: GC_TIME.default,
    placeholderData: keepPreviousData,
    enabled: options.enabled ?? true,
  });

  return toQueryState(query, (data) => data.data.length === 0);
}

/** Aggregate quality for the filtered period. */
export function useQualitySummary(
  filters: QualityFilters = {},
  options: { enabled?: boolean } = {},
): QueryState<QualitySummary> {
  const query = useQuery({
    queryKey: queryKeys.quality.summary(filters),
    queryFn: () => fetchQualitySummary(filters),
    staleTime: STALE_TIME.trend,
    gcTime: GC_TIME.default,
    placeholderData: keepPreviousData,
    enabled: options.enabled ?? true,
  });

  return toQueryState(query, (data) => !data.has_data);
}

/**
 * Pareto-ordered defect breakdown.
 *
 * Arrives sorted with `cumulative_percentage` already computed. Nothing is
 * re-sorted here: the cumulative series depends on position, so re-ordering it
 * client-side would silently produce a wrong Pareto line.
 */
export function useDefectBreakdown(
  filters: DefectBreakdownFilters = {},
  options: { enabled?: boolean } = {},
): QueryState<DefectSummary[]> {
  const query = useQuery({
    queryKey: queryKeys.quality.defects(filters),
    queryFn: () => fetchDefectBreakdown(filters),
    staleTime: STALE_TIME.trend,
    gcTime: GC_TIME.default,
    placeholderData: keepPreviousData,
    enabled: options.enabled ?? true,
  });

  return toQueryState(query);
}

/** Daily defect rate over the filtered period. */
export function useDefectTrend(
  filters: QualityFilters = {},
  options: { enabled?: boolean } = {},
): QueryState<DefectTrendPoint[]> {
  const query = useQuery({
    queryKey: queryKeys.quality.trend(filters),
    queryFn: () => fetchDefectTrend(filters),
    staleTime: STALE_TIME.trend,
    gcTime: GC_TIME.default,
    placeholderData: keepPreviousData,
    enabled: options.enabled ?? true,
  });

  return toQueryState(query);
}

/** Rejection totals grouped by machine or component. */
export function useQualityByDimension(
  dimension: QualityDimension,
  filters: QualityFilters & { limit?: number } = {},
  options: { enabled?: boolean } = {},
): QueryState<QualityByDimension[]> {
  const query = useQuery({
    queryKey: queryKeys.quality.byDimension(dimension, filters),
    queryFn: () => fetchQualityByDimension(dimension, filters),
    staleTime: STALE_TIME.trend,
    gcTime: GC_TIME.default,
    placeholderData: keepPreviousData,
    enabled: options.enabled ?? true,
  });

  return toQueryState(query);
}
