/**
 * Production response models, mirroring `app/schemas/production.py`.
 *
 * Every rate arrives pre-computed. Spec section 42 keeps KPI formulas in the
 * backend, so `efficiency_percentage` and `defect_rate_percentage` are read,
 * never derived here.
 */
import type {
  DateRangeFilters,
  IsoDate,
  IsoDateTime,
  PaginationFilters,
  SortFilters,
  Uuid,
} from "@/types/common";

/** One production run: a machine, a component, a shift, a day. */
export interface ProductionRecord {
  id: Uuid;
  record_date: IsoDate;

  machine_id: Uuid;
  machine_code: string;
  machine_name: string;

  component_id: Uuid;
  component_code: string;
  component_name: string;

  line_id: Uuid;
  line_code: string;
  line_name: string;

  shift_id: Uuid;
  shift_code: string;
  shift_name: string;

  started_at: IsoDateTime;
  ended_at: IsoDateTime;

  planned_quantity: number;
  produced_quantity: number;
  accepted_quantity: number;
  rejected_quantity: number;

  planned_minutes: number;
  operating_minutes: number;
  downtime_minutes: number;

  efficiency_percentage: number;
  defect_rate_percentage: number;
}

/** Aggregate production for a filtered period. */
export interface ProductionSummary {
  start_date: IsoDate;
  end_date: IsoDate;

  total_planned: number;
  total_produced: number;
  total_accepted: number;
  total_rejected: number;

  /**
   * Sum of daily targets.
   *
   * Zero when the filter includes a machine or shift: targets have no such
   * dimension, so the backend suppresses the comparison rather than reporting a
   * misleading achievement figure.
   */
  target_quantity: number;
  achievement_percentage: number;
  efficiency_percentage: number;
  defect_rate_percentage: number;

  total_planned_minutes: number;
  total_operating_minutes: number;
  total_downtime_minutes: number;

  record_count: number;
  /**
   * False when nothing matched the filter.
   *
   * The field that distinguishes "0% because nothing ran" from "0% because
   * everything failed" -- a percentage alone cannot express the difference.
   */
  has_data: boolean;
}

/** One day on the production trend chart. */
export interface ProductionTrendPoint {
  bucket_date: IsoDate;
  planned_quantity: number;
  produced_quantity: number;
  accepted_quantity: number;
  rejected_quantity: number;
  target_quantity: number;
  achievement_percentage: number;
}

/** Production grouped by machine, component, line or shift. */
export interface ProductionByDimension {
  key_id: Uuid;
  key_code: string;
  key_name: string;
  planned_quantity: number;
  produced_quantity: number;
  accepted_quantity: number;
  rejected_quantity: number;
  efficiency_percentage: number;
  defect_rate_percentage: number;
}

/** Filters accepted by the production endpoints. */
export interface ProductionFilters extends DateRangeFilters {
  machine_id?: Uuid;
  component_id?: Uuid;
  shift_id?: Uuid;
  line_id?: Uuid;
}

/** Production list: filters plus pagination and sorting. */
export interface ProductionListFilters extends ProductionFilters, PaginationFilters, SortFilters {}

/**
 * Sort keys the production list accepts.
 *
 * Mirrors the backend allow-list. Typed as a union so an invalid key is a
 * compile error rather than a 422 discovered at runtime -- the server check
 * remains the real defence (spec section 57).
 */
export type ProductionSortKey =
  "date" | "produced" | "planned" | "accepted" | "rejected" | "downtime" | "machine" | "component";

/** Production grouping filters, which carry their own result limit. */
export interface ProductionGroupFilters extends ProductionFilters {
  limit?: number;
}

/** Dimensions the production totals can be grouped by. */
export type ProductionDimension = "machine" | "component" | "shift" | "line";
