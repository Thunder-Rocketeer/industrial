/**
 * Dashboard response models, mirroring `app/schemas/dashboard.py`.
 *
 * `DashboardSummary` is one large composite on purpose: spec section 9 asks for
 * a single endpoint that renders the main screen without many round trips, and
 * the backend runs its nine aggregates concurrently to make that cheap.
 */
import type { Alert, AlertSummary } from "@/types/alerts";
import type { OEEComponents, OEETrendPoint } from "@/types/analytics";
import type { IsoDate, IsoDateTime, Uuid } from "@/types/common";
import type { InventorySummary } from "@/types/inventory";
import type { MachineFleetSummary } from "@/types/machines";
import type { ProductionSummary, ProductionTrendPoint } from "@/types/production";
import type { DefectSummary, DefectTrendPoint, QualitySummary } from "@/types/quality";

/** Movement of a KPI against the previous comparable period. */
export interface KpiTrend {
  /**
   * Null when there is no previous period to compare against.
   *
   * Deliberately nullable: "no comparison available" and "no change" are
   * different facts, and a card reading "0.0% vs yesterday" when yesterday has
   * no data states something false.
   */
  change_percentage: number | null;
  /** Text, so direction is not conveyed by an arrow or a colour alone. */
  direction: "up" | "down" | "flat" | "unknown";
  comparison_label: string;
}

/** Status a KPI card reports. Text, never a colour. */
export type KpiStatus = "good" | "warning" | "critical" | "neutral";

/**
 * One KPI card.
 *
 * Carries everything the card renders -- value, unit, context, status and
 * trend -- because spec section 42 keeps the formulas out of UI components.
 * The frontend formats; it does not calculate.
 */
export interface DashboardKpi {
  key: string;
  label: string;
  value: number;
  unit: string;
  context_label: string;
  status: KpiStatus;
  status_label: string;
  trend: KpiTrend;
}

/** Everything the executive dashboard needs, in one response. */
export interface DashboardSummary {
  generated_at: IsoDateTime;
  /**
   * The date the "today" figures cover.
   *
   * Anchored to the most recent date with production, not the wall clock:
   * seeded demo data ends when it was generated, so a calendar anchor would
   * show an empty dashboard indistinguishable from a broken deployment.
   */
  business_date: IsoDate;

  kpis: DashboardKpi[];

  production: ProductionSummary;
  quality: QualitySummary;
  inventory: InventorySummary;
  machines: MachineFleetSummary;
  oee: OEEComponents;

  alerts: AlertSummary;
  recent_alerts: Alert[];

  /** Whether this response came from the backend Redis cache. */
  cache_hit: boolean;
}

/** Chart series for the dashboard. */
export interface DashboardTrends {
  start_date: IsoDate;
  end_date: IsoDate;

  production: ProductionTrendPoint[];
  defects: DefectTrendPoint[];
  oee: OEETrendPoint[];
  top_defects: DefectSummary[];
  has_data: boolean;
}

/** Filters accepted by the trends endpoint. */
export interface TrendFilters {
  start_date?: IsoDate;
  end_date?: IsoDate;
  line_id?: Uuid;
}
