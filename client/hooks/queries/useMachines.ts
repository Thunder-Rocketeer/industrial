"use client";

/**
 * Machine query hooks.
 */
import { keepPreviousData, useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback } from "react";

import { fetchMachine, fetchMachines, fetchMachineSummary } from "@/lib/api/machines";
import { GC_TIME, STALE_TIME } from "@/lib/constants/cache";
import { queryKeys } from "@/lib/query/query-keys";
import { type QueryState, toQueryState } from "@/lib/query/query-state";
import type { Uuid } from "@/types/common";
import type {
  MachineDetail,
  MachineDetailFilters,
  MachineFilters,
  MachineFleetSummary,
  MachineSummary,
} from "@/types/machines";

/**
 * The machine fleet.
 *
 * Realtime tier: machine status is the most volatile thing on the dashboard,
 * and a board showing a machine as running when it stopped five minutes ago is
 * worse than a board that took an extra moment to load.
 */
export function useMachines(
  filters: MachineFilters = {},
  options: { enabled?: boolean } = {},
): QueryState<MachineSummary[]> {
  const query = useQuery({
    queryKey: queryKeys.machines.list(filters),
    queryFn: () => fetchMachines(filters),
    staleTime: STALE_TIME.realtime,
    gcTime: GC_TIME.default,
    placeholderData: keepPreviousData,
    enabled: options.enabled ?? true,
  });

  return toQueryState(query);
}

/** Fleet counts and overall availability. */
export function useMachineSummary(
  options: { enabled?: boolean } = {},
): QueryState<MachineFleetSummary> {
  const query = useQuery({
    queryKey: queryKeys.machines.summary(),
    queryFn: fetchMachineSummary,
    staleTime: STALE_TIME.realtime,
    gcTime: GC_TIME.default,
    enabled: options.enabled ?? true,
  });

  return toQueryState(query, (data) => data.total_machines === 0);
}

/** One machine with its statistics and maintenance history. */
export function useMachine(
  machineId: Uuid | undefined,
  filters: MachineDetailFilters = {},
  options: { enabled?: boolean } = {},
): QueryState<MachineDetail> {
  const query = useQuery({
    queryKey: queryKeys.machines.detail(machineId ?? "", filters),
    queryFn: () => fetchMachine(machineId as Uuid, filters),
    staleTime: STALE_TIME.realtime,
    gcTime: GC_TIME.default,
    enabled: Boolean(machineId) && (options.enabled ?? true),
  });

  return toQueryState(query, () => false);
}

/**
 * Warm the cache for a machine before the user opens it (spec section 21).
 *
 * Wired to hover or focus on a row in the machines board. The detail request is
 * already in flight by the time the click lands, so the page renders with data
 * rather than a skeleton.
 *
 * `prefetchQuery` is a no-op when the data is already cached and fresh, so
 * repeated hovers over the same row cost nothing. Prefetching is applied only
 * here and on the dashboard, not to every route: fetching pages nobody opens
 * spends the user's bandwidth and the backend's rate limit to no purpose.
 */
export function usePrefetchMachine() {
  const queryClient = useQueryClient();

  return useCallback(
    (machineId: Uuid) => {
      void queryClient.prefetchQuery({
        queryKey: queryKeys.machines.detail(machineId, {}),
        queryFn: () => fetchMachine(machineId),
        staleTime: STALE_TIME.realtime,
      });
    },
    [queryClient],
  );
}
