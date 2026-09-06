/**
 * Production API.
 */
import { get } from "@/lib/api/client";
import { buildParams } from "@/lib/api/params";
import type { ApiEnvelope, PaginatedResponse } from "@/types/api";
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
 * Returns the whole envelope rather than just the rows: the pagination metadata
 * is what a table needs to render its controls, and discarding it here would
 * force the caller to count rows and guess.
 */
export async function fetchProductionRecords(
  filters: ProductionListFilters = {},
): Promise<PaginatedResponse<ProductionRecord>> {
  return get<PaginatedResponse<ProductionRecord>>("/production", {
    params: buildParams(filters),
  });
}

/** Aggregate production for the filtered period. */
export async function fetchProductionSummary(
  filters: ProductionFilters = {},
): Promise<ProductionSummary> {
  const response = await get<ApiEnvelope<ProductionSummary>>("/production/summary", {
    params: buildParams(filters),
  });
  return response.data;
}

/**
 * Daily production totals with the matching target.
 *
 * Days with no production are absent rather than zero, so a chart can
 * distinguish a plant shutdown from a day of total failure.
 */
export async function fetchProductionTrend(
  filters: ProductionFilters = {},
): Promise<ProductionTrendPoint[]> {
  const response = await get<ApiEnvelope<ProductionTrendPoint[]>>("/production/trend", {
    params: buildParams(filters),
  });
  return response.data;
}

/**
 * Production totals grouped by one dimension.
 *
 * The dimension picks the endpoint rather than becoming a query parameter,
 * which is how the backend models it -- there is no route that accepts a
 * caller-supplied grouping column.
 */
export async function fetchProductionByDimension(
  dimension: ProductionDimension,
  filters: ProductionGroupFilters = {},
): Promise<ProductionByDimension[]> {
  const response = await get<ApiEnvelope<ProductionByDimension[]>>(`/production/by-${dimension}`, {
    params: buildParams(filters),
  });
  return response.data;
}
