/**
 * Dashboard API.
 *
 * Uses the shared Axios client from Phase 1 -- no new instance, so credentials,
 * correlation IDs and error normalization apply here exactly as everywhere else
 * (spec section 1).
 */
import { get } from "@/lib/api/client";
import { buildParams } from "@/lib/api/params";
import type { ApiEnvelope } from "@/types/api";
import type { DashboardSummary, DashboardTrends, TrendFilters } from "@/types/dashboard";

/**
 * Everything the executive dashboard needs, in one request.
 *
 * Takes no parameters: the backend anchors the figures to its own business date
 * and caches the result for 30 seconds.
 */
export async function fetchDashboardSummary(): Promise<DashboardSummary> {
  const response = await get<ApiEnvelope<DashboardSummary>>("/dashboard/summary");
  return response.data;
}

/** Chart series for the dashboard. Defaults to the last 30 days. */
export async function fetchDashboardTrends(filters: TrendFilters = {}): Promise<DashboardTrends> {
  const response = await get<ApiEnvelope<DashboardTrends>>("/dashboard/trends", {
    params: buildParams(filters),
  });
  return response.data;
}
