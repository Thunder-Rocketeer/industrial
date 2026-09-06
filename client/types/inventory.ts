/**
 * Inventory response models, mirroring `app/schemas/inventory.py`.
 *
 * `status` is a generated column in the database, computed from the quantity
 * against its thresholds. It is read here and never derived: spec section 10
 * is explicit that inventory health is the backend's answer, and computing it
 * again in the browser would create a second definition that can disagree.
 */
import type {
  InventoryStatus,
  InventoryTransactionType,
  IsoDateTime,
  PaginationFilters,
  SortFilters,
  Uuid,
} from "@/types/common";

/** One stock line. */
export interface InventoryItem {
  id: Uuid;
  sku: string;
  name: string;
  material_type: string;
  unit: string;

  /** Set when the item maps to a manufactured component; null for raw material. */
  component_id: Uuid | null;
  component_code: string | null;
  component_name: string | null;

  current_quantity: number;
  minimum_stock: number;
  reorder_point: number;
  maximum_stock: number;

  status: InventoryStatus;
  /** Display text. Renders instead of the raw enum (spec section 45). */
  status_label: string;
  stock_utilization_percentage: number;

  supplier_name: string;
  supplier_lead_time_days: number | null;
  unit_cost: number | null;
  last_counted_at: IsoDateTime | null;
  updated_at: IsoDateTime;
}

/** A stock line needing attention. A narrower projection than the full item. */
export interface InventoryAlert {
  id: Uuid;
  sku: string;
  name: string;
  unit: string;
  status: InventoryStatus;
  status_label: string;
  current_quantity: number;
  minimum_stock: number;
  reorder_point: number;
  shortfall: number;
  supplier_name: string;
  supplier_lead_time_days: number | null;
  /** A full sentence, readable without colour or an icon. */
  message: string;
}

/** How many stock lines sit in one state. */
export interface InventoryStatusCount {
  status: InventoryStatus;
  status_label: string;
  count: number;
}

/** Aggregate inventory position. */
export interface InventorySummary {
  total_items: number;
  healthy_count: number;
  low_count: number;
  critical_count: number;
  overstocked_count: number;

  health_percentage: number;
  items_requiring_attention: number;
  /** Null when any item has no unit cost: a partial sum is not a total. */
  total_stock_value: number | null;
  status_breakdown: InventoryStatusCount[];
}

/** One stock movement. `quantity_delta` is signed. */
export interface InventoryTransaction {
  id: Uuid;
  inventory_item_id: Uuid;
  transaction_type: InventoryTransactionType;
  quantity_delta: number;
  balance_after: number;
  reference: string;
  notes: string;
  occurred_at: IsoDateTime;
}

/** One point on an item's stock-level history. */
export interface InventoryTrendPoint {
  bucket_date: IsoDateTime;
  balance: number;
}

/** Filters accepted by the inventory list. */
export interface InventoryFilters extends PaginationFilters, SortFilters {
  status?: InventoryStatus;
  component_id?: Uuid;
}

/** Sort keys the inventory list accepts. Mirrors the backend allow-list. */
export type InventorySortKey = "name" | "sku" | "status" | "quantity" | "updated";
