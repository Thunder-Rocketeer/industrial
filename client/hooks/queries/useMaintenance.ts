"use client";

/**
 * Maintenance query hooks.
 */
import { keepPreviousData, useQuery } from "@tanstack/react-query";

import { fetchMaintenanceRecords } from "@/lib/api/maintenance";
import { GC_TIME, STALE_TIME } from "@/lib/constants/cache";
import { queryKeys } from "@/lib/query/query-keys";
import { type QueryState, toQueryState } from "@/lib/query/query-state";
import type { PaginatedResponse } from "@/types/api";
import type { MaintenanceFilters, MaintenanceRecord } from "@/types/maintenance";

/**
 * One page of maintenance jobs.
 *
 * `upcoming_only` changes the ordering server-side as well as the filter, so it
 * is part of the query key and produces a separate cache entry -- history and
 * upcoming work are two different lists, not two views of one.
 */
export function useMaintenanceRecords(
  filters: MaintenanceFilters = {},
  options: { enabled?: boolean } = {},
): QueryState<PaginatedResponse<MaintenanceRecord>> {
  const query = useQuery({
    queryKey: queryKeys.maintenance.list(filters),
    queryFn: () => fetchMaintenanceRecords(filters),
    staleTime: STALE_TIME.trend,
    gcTime: GC_TIME.default,
    placeholderData: keepPreviousData,
    enabled: options.enabled ?? true,
  });

  return toQueryState(query, (data) => data.data.length === 0);
}

/** Scheduled and in-progress work, soonest first. */
export function useUpcomingMaintenance(
  filters: Omit<MaintenanceFilters, "upcoming_only"> = {},
  options: { enabled?: boolean } = {},
): QueryState<PaginatedResponse<MaintenanceRecord>> {
  return useMaintenanceRecords({ ...filters, upcoming_only: true }, options);
}
