"use client";

/**
 * Inventory query hooks.
 *
 * Stock status and health are read from the response, never derived. Spec
 * section 10: "Do not calculate inventory health client-side. Use the backend
 * status/health result." The database computes `status` from the quantity and
 * its thresholds, so a second definition here could only disagree with it.
 */
import { keepPreviousData, useQuery } from "@tanstack/react-query";

import {
  fetchInventoryAlerts,
  fetchInventoryItem,
  fetchInventoryItems,
  fetchInventorySummary,
  fetchInventoryTransactions,
  fetchInventoryTrend,
} from "@/lib/api/inventory";
import { GC_TIME, STALE_TIME } from "@/lib/constants/cache";
import { queryKeys } from "@/lib/query/query-keys";
import { type QueryState, toQueryState } from "@/lib/query/query-state";
import type { PaginatedResponse } from "@/types/api";
import type { PaginationFilters, Uuid } from "@/types/common";
import type {
  InventoryAlert,
  InventoryFilters,
  InventoryItem,
  InventorySummary,
  InventoryTransaction,
  InventoryTrendPoint,
} from "@/types/inventory";

/** One page of stock lines. */
export function useInventoryItems(
  filters: InventoryFilters = {},
  options: { enabled?: boolean } = {},
): QueryState<PaginatedResponse<InventoryItem>> {
  const query = useQuery({
    queryKey: queryKeys.inventory.list(filters),
    queryFn: () => fetchInventoryItems(filters),
    staleTime: STALE_TIME.trend,
    gcTime: GC_TIME.default,
    placeholderData: keepPreviousData,
    enabled: options.enabled ?? true,
  });

  return toQueryState(query, (data) => data.data.length === 0);
}

/**
 * Stock lines needing attention.
 *
 * Realtime tier: this drives the alerts panel, and a stale critical-stock
 * warning is the one piece of inventory data where lag actually matters.
 */
export function useInventoryAlerts(
  limit?: number,
  options: { enabled?: boolean } = {},
): QueryState<InventoryAlert[]> {
  const query = useQuery({
    queryKey: queryKeys.inventory.alerts(limit),
    queryFn: () => fetchInventoryAlerts(limit),
    staleTime: STALE_TIME.realtime,
    gcTime: GC_TIME.default,
    enabled: options.enabled ?? true,
  });

  // An empty alert list is good news, and worth its own state: "nothing needs
  // attention" reads very differently from a panel that failed to load.
  return toQueryState(query);
}

/** Counts per stock state and the overall health percentage. */
export function useInventorySummary(
  options: { enabled?: boolean } = {},
): QueryState<InventorySummary> {
  const query = useQuery({
    queryKey: queryKeys.inventory.summary(),
    queryFn: fetchInventorySummary,
    staleTime: STALE_TIME.realtime,
    gcTime: GC_TIME.default,
    enabled: options.enabled ?? true,
  });

  return toQueryState(query, (data) => data.total_items === 0);
}

/** One stock line. */
export function useInventoryItem(
  itemId: Uuid | undefined,
  options: { enabled?: boolean } = {},
): QueryState<InventoryItem> {
  const query = useQuery({
    queryKey: queryKeys.inventory.detail(itemId ?? ""),
    queryFn: () => fetchInventoryItem(itemId as Uuid),
    staleTime: STALE_TIME.trend,
    gcTime: GC_TIME.default,
    // Guarded rather than fetched with an empty id: a request to
    // `/inventory/` would 404 and surface as an error the user cannot act on.
    enabled: Boolean(itemId) && (options.enabled ?? true),
  });

  return toQueryState(query, () => false);
}

/** One page of stock movements for an item. */
export function useInventoryTransactions(
  itemId: Uuid | undefined,
  filters: PaginationFilters = {},
  options: { enabled?: boolean } = {},
): QueryState<PaginatedResponse<InventoryTransaction>> {
  const query = useQuery({
    queryKey: queryKeys.inventory.transactions(itemId ?? "", filters),
    queryFn: () => fetchInventoryTransactions(itemId as Uuid, filters),
    staleTime: STALE_TIME.trend,
    gcTime: GC_TIME.default,
    placeholderData: keepPreviousData,
    enabled: Boolean(itemId) && (options.enabled ?? true),
  });

  return toQueryState(query, (data) => data.data.length === 0);
}

/** Closing balance per day, for the stock trend chart. */
export function useInventoryTrend(
  itemId: Uuid | undefined,
  limit?: number,
  options: { enabled?: boolean } = {},
): QueryState<InventoryTrendPoint[]> {
  const query = useQuery({
    queryKey: queryKeys.inventory.trend(itemId ?? "", limit),
    queryFn: () => fetchInventoryTrend(itemId as Uuid, limit),
    staleTime: STALE_TIME.trend,
    gcTime: GC_TIME.default,
    enabled: Boolean(itemId) && (options.enabled ?? true),
  });

  return toQueryState(query);
}
