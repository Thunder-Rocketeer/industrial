/**
 * Alert response models, mirroring `app/schemas/alerts.py`.
 *
 * Every alert carries a title, a full-sentence description and a severity
 * label. Spec section 34 requires all three, and spec section 45 requires that
 * severity is readable as text rather than conveyed by a colour.
 */
import type {
  AlertSeverity,
  AlertStatus,
  AlertType,
  IsoDateTime,
  PaginationFilters,
  Uuid,
} from "@/types/common";

/** One operational alert. */
export interface Alert {
  id: Uuid;
  alert_type: AlertType;
  alert_type_label: string;
  severity: AlertSeverity;
  severity_label: string;
  status: AlertStatus;
  status_label: string;

  title: string;
  /** A full sentence. Never empty; a database constraint enforces it. */
  description: string;

  /** At least one subject is always set. */
  machine_id: Uuid | null;
  machine_code: string | null;
  machine_name: string | null;
  component_id: Uuid | null;
  component_name: string | null;
  inventory_item_id: Uuid | null;
  inventory_item_name: string | null;
  line_id: Uuid | null;
  line_name: string | null;

  triggered_at: IsoDateTime;
  acknowledged_at: IsoDateTime | null;
  resolved_at: IsoDateTime | null;
  age_minutes: number;
}

/** How many open alerts sit at one severity. */
export interface AlertSeverityCount {
  severity: AlertSeverity;
  severity_label: string;
  count: number;
}

/** Counts for the dashboard alerts panel. */
export interface AlertSummary {
  total_open: number;
  critical_count: number;
  warning_count: number;
  info_count: number;
  acknowledged_count: number;
  severity_breakdown: AlertSeverityCount[];
}

/** Filters accepted by the alerts list. */
export interface AlertFilters extends PaginationFilters {
  status?: AlertStatus;
  severity?: AlertSeverity;
  machine_id?: Uuid;
}
