/**
 * Quality response models, mirroring `app/schemas/quality.py`.
 *
 * One schema fact shapes everything here: `quality_records` has two row shapes.
 * A pass line has `defect_id: null` and carries the accepted units; each
 * further line names one defect and carries its rejections. `is_rejection`
 * distinguishes them so a component never has to infer it from a null check.
 */
import type {
  DateRangeFilters,
  DefectSeverity,
  IsoDate,
  IsoDateTime,
  PaginationFilters,
  SortFilters,
  Uuid,
} from "@/types/common";

/** One inspection line. */
export interface QualityRecord {
  id: Uuid;
  production_record_id: Uuid;
  inspected_at: IsoDateTime;

  machine_id: Uuid;
  machine_code: string;
  component_id: Uuid;
  component_code: string;
  component_name: string;

  /** Null on the pass line, set on a rejection line. */
  defect_id: Uuid | null;
  defect_code: string | null;
  defect_name: string | null;
  severity: DefectSeverity | null;

  inspected_quantity: number;
  passed_quantity: number;
  rejected_quantity: number;
  /** Units passing with no rework. Non-zero only on the pass line. */
  first_pass_quantity: number;
  rework_quantity: number;

  /** True when this line records a defect. Derived server-side. */
  is_rejection: boolean;
}

/** Aggregate quality for a filtered period. */
export interface QualitySummary {
  start_date: IsoDate;
  end_date: IsoDate;

  total_inspected: number;
  total_passed: number;
  total_rejected: number;
  total_first_pass: number;
  total_rework: number;

  defect_rate_percentage: number;
  /**
   * First-pass units over *all* units inspected, not just those that passed.
   * Always at or below the quality rate; rework is what separates them.
   */
  first_pass_yield_percentage: number;
  quality_rate_percentage: number;

  distinct_defect_types: number;
  record_count: number;
  has_data: boolean;
}

/**
 * One defect category's contribution, for the Pareto chart.
 *
 * `cumulative_percentage` is computed server-side over the sorted set. It
 * depends on a row's position, which is exactly the thing that goes wrong when
 * each chart recalculates it from a differently sorted or truncated copy.
 */
export interface DefectSummary {
  defect_id: Uuid;
  defect_code: string;
  defect_name: string;
  category: string;
  default_severity: DefectSeverity;

  rejected_quantity: number;
  occurrence_count: number;
  share_percentage: number;
  cumulative_percentage: number;
}

/** One day on the defect trend chart. */
export interface DefectTrendPoint {
  bucket_date: IsoDate;
  inspected_quantity: number;
  rejected_quantity: number;
  defect_rate_percentage: number;
}

/** Rejection totals grouped by machine or component. */
export interface QualityByDimension {
  key_id: Uuid;
  key_code: string;
  key_name: string;
  inspected_quantity: number;
  rejected_quantity: number;
  defect_rate_percentage: number;
}

/** Filters accepted by the quality endpoints. */
export interface QualityFilters extends DateRangeFilters {
  machine_id?: Uuid;
  component_id?: Uuid;
  defect_id?: Uuid;
}

/** Quality list: filters plus pagination, sorting and the rejection switch. */
export interface QualityListFilters extends QualityFilters, PaginationFilters, SortFilters {
  /** Return only lines that recorded a defect. */
  rejections_only?: boolean;
}

/** Sort keys the quality list accepts. Mirrors the backend allow-list. */
export type QualitySortKey =
  "inspected_at" | "inspected" | "rejected" | "passed" | "machine" | "component";

/** Defect breakdown filters, which carry their own result limit. */
export interface DefectBreakdownFilters extends QualityFilters {
  limit?: number;
}

/** Dimensions quality totals can be grouped by. */
export type QualityDimension = "machine" | "component";
