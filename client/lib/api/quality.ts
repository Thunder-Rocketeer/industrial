/**
 * Quality API.
 */
import { get } from "@/lib/api/client";
import { buildParams } from "@/lib/api/params";
import type { ApiEnvelope, PaginatedResponse } from "@/types/api";
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
export async function fetchQualityRecords(
  filters: QualityListFilters = {},
): Promise<PaginatedResponse<QualityRecord>> {
  return get<PaginatedResponse<QualityRecord>>("/quality", {
    params: buildParams(filters),
  });
}

/** Aggregate quality for the filtered period. */
export async function fetchQualitySummary(filters: QualityFilters = {}): Promise<QualitySummary> {
  const response = await get<ApiEnvelope<QualitySummary>>("/quality/summary", {
    params: buildParams(filters),
  });
  return response.data;
}

/**
 * Pareto-ordered defect breakdown.
 *
 * Arrives sorted with the cumulative percentage already computed, so a chart
 * plots it directly.
 */
export async function fetchDefectBreakdown(
  filters: DefectBreakdownFilters = {},
): Promise<DefectSummary[]> {
  const response = await get<ApiEnvelope<DefectSummary[]>>("/quality/defects", {
    params: buildParams(filters),
  });
  return response.data;
}

/** Daily defect rate over the filtered period. */
export async function fetchDefectTrend(filters: QualityFilters = {}): Promise<DefectTrendPoint[]> {
  const response = await get<ApiEnvelope<DefectTrendPoint[]>>("/quality/trend", {
    params: buildParams(filters),
  });
  return response.data;
}

/** Rejection totals grouped by machine or component. */
export async function fetchQualityByDimension(
  dimension: QualityDimension,
  filters: QualityFilters & { limit?: number } = {},
): Promise<QualityByDimension[]> {
  const response = await get<ApiEnvelope<QualityByDimension[]>>(`/quality/by-${dimension}`, {
    params: buildParams(filters),
  });
  return response.data;
}
