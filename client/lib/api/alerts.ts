/**
 * Alerts API.
 */
import { get } from "@/lib/api/client";
import { buildParams } from "@/lib/api/params";
import type { ApiEnvelope, PaginatedResponse } from "@/types/api";
import type { Alert, AlertFilters, AlertSummary } from "@/types/alerts";

/** One page of alerts, most severe and most recent first. */
export async function fetchAlerts(filters: AlertFilters = {}): Promise<PaginatedResponse<Alert>> {
  return get<PaginatedResponse<Alert>>("/alerts", { params: buildParams(filters) });
}

/** Open alerts only, for the dashboard panel. */
export async function fetchActiveAlerts(limit?: number): Promise<Alert[]> {
  const response = await get<ApiEnvelope<Alert[]>>("/alerts/active", {
    params: buildParams({ limit }),
  });
  return response.data;
}

/** Counts of open alerts by severity. */
export async function fetchAlertSummary(): Promise<AlertSummary> {
  const response = await get<ApiEnvelope<AlertSummary>>("/alerts/summary");
  return response.data;
}
