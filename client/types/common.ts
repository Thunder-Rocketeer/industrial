/**
 * Enumerations and shared primitives, mirroring `app/models/enums.py`.
 *
 * These are the vocabulary the API speaks. Declared as string-literal unions
 * rather than TypeScript `enum`s: a union is erased at build time, compares
 * directly against the JSON the API returns, and does not create a runtime
 * object that can drift from the server's idea of the same values.
 *
 * Every status value arrives from the API paired with a `*_label` field. The
 * label is what gets rendered -- spec section 45 requires state to be readable
 * as text, and the backend owns that text so two components cannot describe the
 * same status differently.
 */

// =============================================================================
// Enumerations
// =============================================================================

/** Live operational state of a machine. */
export type MachineStatus = "RUNNING" | "IDLE" | "MAINTENANCE" | "OFFLINE";

/** Machine capability class. */
export type MachineType =
  | "CNC_TURNING_CENTER"
  | "CNC_MILLING_CENTER"
  | "VERTICAL_MACHINING_CENTER"
  | "GRINDING_MACHINE"
  | "HEAT_TREATMENT_UNIT"
  | "INSPECTION_STATION"
  | "ASSEMBLY_STATION";

/** Stock health. Derived by the database, never computed in the browser. */
export type InventoryStatus = "HEALTHY" | "LOW" | "CRITICAL" | "OVERSTOCKED";

/** Direction and reason for a stock movement. */
export type InventoryTransactionType = "RECEIPT" | "ISSUE" | "RETURN" | "SCRAP" | "ADJUSTMENT";

export type MaintenanceType = "PREVENTIVE" | "CORRECTIVE" | "PREDICTIVE" | "CALIBRATION";

export type MaintenanceStatus = "SCHEDULED" | "IN_PROGRESS" | "COMPLETED" | "CANCELLED";

/** How serious a defect occurrence is. */
export type DefectSeverity = "MINOR" | "MAJOR" | "CRITICAL";

export type AlertType =
  | "CRITICAL_INVENTORY"
  | "LOW_INVENTORY"
  | "MAINTENANCE_DUE"
  | "MAINTENANCE_OVERDUE"
  | "PRODUCTION_TARGET_RISK"
  | "HIGH_DEFECT_RATE"
  | "MACHINE_OFFLINE";

export type AlertSeverity = "INFO" | "WARNING" | "CRITICAL";

export type AlertStatus = "OPEN" | "ACKNOWLEDGED" | "RESOLVED";

/** Sort direction accepted by list endpoints. */
export type SortDirection = "asc" | "desc";

// =============================================================================
// Primitives
// =============================================================================

/**
 * A UUID, as the API sends it.
 *
 * An alias rather than a branded type: branding would require a validating
 * constructor at every boundary, and the values here come from the API rather
 * than from user input. The backend rejects a malformed UUID with 422 long
 * before it could matter.
 */
export type Uuid = string;

/** An ISO-8601 date, `YYYY-MM-DD`. Always UTC. */
export type IsoDate = string;

/** An ISO-8601 timestamp with offset. Always UTC from the API. */
export type IsoDateTime = string;

// =============================================================================
// Shared filter shapes
// =============================================================================

/**
 * An inclusive date window.
 *
 * Both optional. Omitting them gives the backend's default window (30 days);
 * the span is capped server-side at 366 days.
 */
export interface DateRangeFilters {
  start_date?: IsoDate;
  end_date?: IsoDate;
}

/** Pagination. `page_size` is capped at 100 by the backend. */
export interface PaginationFilters {
  page?: number;
  page_size?: number;
}

/** Sorting. `sort_by` must be an allow-listed key; anything else is a 422. */
export interface SortFilters {
  sort_by?: string;
  sort_dir?: SortDirection;
}

/**
 * A textual status paired with its display label.
 *
 * The shape every enum-valued field takes in a response. Modelled explicitly so
 * a component cannot accidentally render the raw code -- spec section 45
 * forbids conveying state by colour or a bare enum alone.
 */
export interface LabelledStatus<TStatus extends string> {
  status: TStatus;
  status_label: string;
}
