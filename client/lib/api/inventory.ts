/**
 * Inventory API.
 *
 * Stock status and health come from the backend and are never recomputed here
 * (spec section 10). The database derives `status` from the quantity and its
 * thresholds, so a second definition in the browser could only disagree.
 */
import { get } from "@/lib/api/client";
import { buildParams } from "@/lib/api/params";
import type { ApiEnvelope, PaginatedResponse } from "@/types/api";
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
export async function fetchInventoryItems(
  filters: InventoryFilters = {},
): Promise<PaginatedResponse<InventoryItem>> {
  return get<PaginatedResponse<InventoryItem>>("/inventory", {
    params: buildParams(filters),
  });
}

/** Stock lines that are CRITICAL or LOW, most urgent first. */
export async function fetchInventoryAlerts(limit?: number): Promise<InventoryAlert[]> {
  const response = await get<ApiEnvelope<InventoryAlert[]>>("/inventory/alerts", {
    params: buildParams({ limit }),
  });
  return response.data;
}

/** Counts per stock state and the overall health percentage. */
export async function fetchInventorySummary(): Promise<InventorySummary> {
  const response = await get<ApiEnvelope<InventorySummary>>("/inventory/summary");
  return response.data;
}

/** One stock line. */
export async function fetchInventoryItem(itemId: Uuid): Promise<InventoryItem> {
  const response = await get<ApiEnvelope<InventoryItem>>(`/inventory/${itemId}`);
  return response.data;
}

/** One page of stock movements for an item, newest first. */
export async function fetchInventoryTransactions(
  itemId: Uuid,
  filters: PaginationFilters = {},
): Promise<PaginatedResponse<InventoryTransaction>> {
  return get<PaginatedResponse<InventoryTransaction>>(`/inventory/${itemId}/transactions`, {
    params: buildParams(filters),
  });
}

/** Closing balance per day, for the stock trend chart. */
export async function fetchInventoryTrend(
  itemId: Uuid,
  limit?: number,
): Promise<InventoryTrendPoint[]> {
  const response = await get<ApiEnvelope<InventoryTrendPoint[]>>(`/inventory/${itemId}/trend`, {
    params: buildParams({ limit }),
  });
  return response.data;
}
