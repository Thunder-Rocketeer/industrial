/**
 * Analytics response models, mirroring `app/schemas/analytics.py`.
 *
 * OEE always arrives with its three terms. Spec section 12 forbids duplicating
 * the calculation here, and spec section 5.6 requires the terms be shown
 * separately -- a single OEE number says something moved, not whether to look
 * at breakdowns, cycle times or scrap.
 */
import type { DateRangeFilters, IsoDate, Uuid } from "@/types/common";
import type { DefectSummary, DefectTrendPoint, QualityByDimension } from "@/types/quality";

/** The three OEE terms and their product. Each capped at 100%. */
export interface OEEComponents {
  availability_percentage: number;
  performance_percentage: number;
  quality_percentage: number;
  oee_percentage: number;
  /**
   * Performance before capping.
   *
   * Above 100 means a recorded ideal cycle time is shorter than the machine can
   * really achieve -- a reference-data problem, not a machine outperforming
   * physics. Surfaced so the problem stays visible rather than hidden by the cap.
   */
  performance_uncapped_percentage: number;
}

/** OEE across a filtered period, with the inputs it came from. */
export interface OEESummary extends OEEComponents {
  start_date: IsoDate;
  end_date: IsoDate;

  operating_minutes: number;
  planned_minutes: number;
  downtime_minutes: number;
  produced_quantity: number;
  accepted_quantity: number;
  rejected_quantity: number;
  ideal_output: number;

  record_count: number;
  has_data: boolean;
}

/** One day on the OEE trend chart. */
export interface OEETrendPoint extends OEEComponents {
  bucket_date: IsoDate;
}

/** OEE for one machine, for fleet comparison. Returned worst first. */
export interface OEEByMachine extends OEEComponents {
  machine_id: Uuid;
  machine_code: string;
  machine_name: string;
  produced_quantity: number;
  operating_minutes: number;
}

/** Production efficiency against plan and target. */
export interface EfficiencySummary {
  start_date: IsoDate;
  end_date: IsoDate;

  total_planned: number;
  total_produced: number;
  total_target: number;

  efficiency_percentage: number;
  /** Zero when the filter includes a machine; targets have no such dimension. */
  achievement_percentage: number;

  total_planned_minutes: number;
  total_operating_minutes: number;
  total_downtime_minutes: number;
  downtime_percentage: number;

  record_count: number;
  has_data: boolean;
}

/** One day on the efficiency trend chart. */
export interface EfficiencyTrendPoint {
  bucket_date: IsoDate;
  planned_quantity: number;
  produced_quantity: number;
  target_quantity: number;
  efficiency_percentage: number;
  achievement_percentage: number;
}

/** Downtime attributed to one machine. Returned worst first. */
export interface DowntimeByMachine {
  machine_id: Uuid;
  machine_code: string;
  machine_name: string;
  downtime_minutes: number;
  planned_minutes: number;
  downtime_percentage: number;
}

/** Full defect analysis: Pareto, by machine, by component, and trend. */
export interface DefectAnalytics {
  start_date: IsoDate;
  end_date: IsoDate;

  total_inspected: number;
  total_rejected: number;
  defect_rate_percentage: number;

  by_defect: DefectSummary[];
  by_machine: QualityByDimension[];
  by_component: QualityByDimension[];
  trend: DefectTrendPoint[];
  has_data: boolean;
}

/** Filters accepted by the analytics endpoints. */
export interface AnalyticsFilters extends DateRangeFilters {
  machine_id?: Uuid;
  component_id?: Uuid;
  line_id?: Uuid;
}
