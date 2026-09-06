/**
 * Maintenance API.
 */
import { get } from "@/lib/api/client";
import { buildParams } from "@/lib/api/params";
import type { PaginatedResponse } from "@/types/api";
import type { MaintenanceFilters, MaintenanceRecord } from "@/types/maintenance";

/**
 * One page of maintenance jobs.
 *
 * `upcoming_only` also flips the ordering server-side: history comes back
 * newest-first, upcoming work soonest-first.
 */
export async function fetchMaintenanceRecords(
  filters: MaintenanceFilters = {},
): Promise<PaginatedResponse<MaintenanceRecord>> {
  return get<PaginatedResponse<MaintenanceRecord>>("/maintenance", {
    params: buildParams(filters),
  });
}
