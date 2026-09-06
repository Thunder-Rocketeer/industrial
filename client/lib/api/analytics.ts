/**
 * Analytics API.
 *
 * Every figure here is calculated by the backend. Spec section 12 forbids
 * duplicating the OEE calculation in the frontend, and the three terms arrive
 * alongside the product so a change can be attributed without recomputing
 * anything.
 */
import { get } from "@/lib/api/client";
import { buildParams } from "@/lib/api/params";
import type { ApiEnvelope } from "@/types/api";
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
export async function fetchOee(filters: AnalyticsFilters = {}): Promise<OEESummary> {
  const response = await get<ApiEnvelope<OEESummary>>("/analytics/oee", {
    params: buildParams(filters),
  });
  return response.data;
}

/** Daily OEE for the trend chart. */
export async function fetchOeeTrend(filters: AnalyticsFilters = {}): Promise<OEETrendPoint[]> {
  const response = await get<ApiEnvelope<OEETrendPoint[]>>("/analytics/oee/trend", {
    params: buildParams(filters),
  });
  return response.data;
}

/** OEE per machine, lowest first so problems appear at the top. */
export async function fetchOeeByMachine(filters: AnalyticsFilters = {}): Promise<OEEByMachine[]> {
  const response = await get<ApiEnvelope<OEEByMachine[]>>("/analytics/oee/by-machine", {
    params: buildParams(filters),
  });
  return response.data;
}

/** Production efficiency against plan and target. */
export async function fetchProductionEfficiency(
  filters: AnalyticsFilters = {},
): Promise<EfficiencySummary> {
  const response = await get<ApiEnvelope<EfficiencySummary>>("/analytics/production-efficiency", {
    params: buildParams(filters),
  });
  return response.data;
}

/** Daily efficiency and target achievement. */
export async function fetchEfficiencyTrend(
  filters: AnalyticsFilters = {},
): Promise<EfficiencyTrendPoint[]> {
  const response = await get<ApiEnvelope<EfficiencyTrendPoint[]>>(
    "/analytics/production-efficiency/trend",
    { params: buildParams(filters) },
  );
  return response.data;
}

/** Downtime per machine, worst first. */
export async function fetchDowntimeByMachine(
  filters: AnalyticsFilters = {},
): Promise<DowntimeByMachine[]> {
  const response = await get<ApiEnvelope<DowntimeByMachine[]>>("/analytics/downtime", {
    params: buildParams(filters),
  });
  return response.data;
}

/** Complete defect analysis: Pareto, by machine, by component, and trend. */
export async function fetchDefectAnalytics(
  filters: AnalyticsFilters = {},
): Promise<DefectAnalytics> {
  const response = await get<ApiEnvelope<DefectAnalytics>>("/analytics/defects", {
    params: buildParams(filters),
  });
  return response.data;
}
