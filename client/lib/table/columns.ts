/**
 * Typed column definitions for the dashboard's data tables (spec section 24).
 *
 * Two rules shape every definition here:
 *
 * 1. **A sortable column's `id` is the backend's sort key, not the field name.**
 *    The API accepts an allow-list of keys -- `date`, `produced`, `efficiency`
 *    and so on (`app/schemas/filters.py`) -- and rejects anything else with a
 *    422. `useServerTable` sends the column id straight through as `sort_by`,
 *    so a column whose id is not on that list would make the table 422 the
 *    moment its header is clicked. Columns the API cannot sort by declare
 *    `enableSorting: false`, so the header renders as plain text and the user
 *    is never offered a control that does not work.
 *
 * 2. **Cells format; they do not compute.** Every percentage, rate and label
 *    below is read from the row exactly as the backend sent it. Deriving one --
 *    `rejected / produced`, say -- would put a second definition of a metric in
 *    the UI, and it would disagree with the KPI card above it on precisely the
 *    rows where the difference matters.
 *
 * Definitions are built inside functions rather than exported as constants
 * because `createColumnHelper` is generic per row type and the resulting arrays
 * are memoized by the caller.
 */
import { type DashboardColumnDef, columnHelperFor } from "@/lib/table/features";
import {
  formatCurrency,
  formatDate,
  formatDateTime,
  formatMinutes,
  formatNumber,
  formatPercentage,
  formatQuantity,
  formatText,
} from "@/lib/utils/format";
import type { Alert } from "@/types/alerts";
import type { InventoryItem } from "@/types/inventory";
import type { MachineSummary, MaintenanceRecord } from "@/types/machines";
import type { ProductionRecord } from "@/types/production";
import type { QualityRecord } from "@/types/quality";

// =============================================================================
// Production
// =============================================================================

/** Sort keys accepted by `GET /production/records`. */
export const PRODUCTION_SORT_KEYS = [
  "date",
  "produced",
  "planned",
  "accepted",
  "rejected",
  "downtime",
  "efficiency",
] as const;

export function productionColumns(): DashboardColumnDef<ProductionRecord>[] {
  const column = columnHelperFor<ProductionRecord>();

  return [
    column.accessor("record_date", {
      id: "date",
      header: "Date",
      cell: (info) => formatDate(info.getValue()),
    }),
    column.accessor("machine_code", {
      id: "machine_code",
      header: "Machine",
      enableSorting: false,
      cell: (info) => info.getValue(),
    }),
    column.accessor("component_name", {
      id: "component_name",
      header: "Component",
      enableSorting: false,
      cell: (info) => info.getValue(),
    }),
    column.accessor("shift_name", {
      id: "shift_name",
      header: "Shift",
      enableSorting: false,
      cell: (info) => info.getValue(),
    }),
    column.accessor("planned_quantity", {
      id: "planned",
      header: "Planned",
      cell: (info) => formatNumber(info.getValue()),
    }),
    column.accessor("produced_quantity", {
      id: "produced",
      header: "Produced",
      cell: (info) => formatNumber(info.getValue()),
    }),
    column.accessor("accepted_quantity", {
      id: "accepted",
      header: "Accepted",
      cell: (info) => formatNumber(info.getValue()),
    }),
    column.accessor("rejected_quantity", {
      id: "rejected",
      header: "Rejected",
      cell: (info) => formatNumber(info.getValue()),
    }),
    column.accessor("downtime_minutes", {
      id: "downtime",
      header: "Downtime",
      cell: (info) => formatMinutes(info.getValue()),
    }),
    column.accessor("efficiency_percentage", {
      id: "efficiency",
      header: "Efficiency",
      cell: (info) => formatPercentage(info.getValue()),
    }),
    column.accessor("defect_rate_percentage", {
      id: "defect_rate",
      header: "Defect rate",
      // Not on the API's sort allow-list.
      enableSorting: false,
      cell: (info) => formatPercentage(info.getValue(), 2),
    }),
  ];
}

// =============================================================================
// Quality
// =============================================================================

/** Sort keys accepted by `GET /quality/records`. */
export const QUALITY_SORT_KEYS = ["inspected_at", "inspected", "rejected", "passed"] as const;

export function qualityColumns(): DashboardColumnDef<QualityRecord>[] {
  const column = columnHelperFor<QualityRecord>();

  return [
    column.accessor("inspected_at", {
      id: "inspected_at",
      header: "Inspected",
      cell: (info) => formatDateTime(info.getValue()),
    }),
    column.accessor("machine_code", {
      id: "machine_code",
      header: "Machine",
      enableSorting: false,
      cell: (info) => info.getValue(),
    }),
    column.accessor("component_name", {
      id: "component_name",
      header: "Component",
      enableSorting: false,
      cell: (info) => info.getValue(),
    }),
    // Null on a pass line, which is a real state and not missing data: the
    // inspection happened and found nothing wrong.
    column.accessor("defect_name", {
      id: "defect_name",
      header: "Defect",
      enableSorting: false,
      cell: (info) => (info.row.original.is_rejection ? formatText(info.getValue()) : "None"),
    }),
    column.accessor("severity", {
      id: "severity",
      header: "Severity",
      enableSorting: false,
      cell: (info) => formatText(info.getValue()),
    }),
    column.accessor("inspected_quantity", {
      id: "inspected",
      header: "Inspected",
      cell: (info) => formatNumber(info.getValue()),
    }),
    column.accessor("passed_quantity", {
      id: "passed",
      header: "Passed",
      cell: (info) => formatNumber(info.getValue()),
    }),
    column.accessor("rejected_quantity", {
      id: "rejected",
      header: "Rejected",
      cell: (info) => formatNumber(info.getValue()),
    }),
    column.accessor("rework_quantity", {
      id: "rework",
      header: "Rework",
      enableSorting: false,
      cell: (info) => formatNumber(info.getValue()),
    }),
  ];
}

// =============================================================================
// Inventory
// =============================================================================

/** Sort keys accepted by `GET /inventory/items`. */
export const INVENTORY_SORT_KEYS = ["name", "sku", "status", "quantity", "utilization"] as const;

export function inventoryColumns(): DashboardColumnDef<InventoryItem>[] {
  const column = columnHelperFor<InventoryItem>();

  return [
    column.accessor("sku", {
      id: "sku",
      header: "SKU",
      cell: (info) => info.getValue(),
    }),
    column.accessor("name", {
      id: "name",
      header: "Item",
      cell: (info) => info.getValue(),
    }),
    column.accessor("material_type", {
      id: "material_type",
      header: "Type",
      enableSorting: false,
      cell: (info) => info.getValue(),
    }),
    column.accessor("current_quantity", {
      id: "quantity",
      header: "On hand",
      cell: (info) => formatQuantity(info.getValue(), info.row.original.unit),
    }),
    column.accessor("reorder_point", {
      id: "reorder_point",
      header: "Reorder at",
      enableSorting: false,
      cell: (info) => formatQuantity(info.getValue(), info.row.original.unit),
    }),
    // The backend classifies stock health (spec section 11: "do not calculate
    // inventory health client-side"). This column renders that verdict; it does
    // not compare quantity against the thresholds beside it.
    column.accessor("status_label", {
      id: "status",
      header: "Status",
      cell: (info) => info.getValue(),
    }),
    column.accessor("stock_utilization_percentage", {
      id: "utilization",
      header: "Utilization",
      cell: (info) => formatPercentage(info.getValue()),
    }),
    column.accessor("supplier_name", {
      id: "supplier_name",
      header: "Supplier",
      enableSorting: false,
      cell: (info) => formatText(info.getValue()),
    }),
    column.accessor("supplier_lead_time_days", {
      id: "lead_time",
      header: "Lead time",
      enableSorting: false,
      cell: (info) => {
        const days = info.getValue();
        return days === null ? formatText(null) : `${formatNumber(days)} days`;
      },
    }),
  ];
}

// =============================================================================
// Machines
// =============================================================================

/**
 * The machine list is unpaginated and ordered by the backend -- the fleet is
 * a dozen machines, not a dataset. These columns are therefore rendered without
 * `useServerTable`, and none of them are sortable server-side.
 */
export function machineColumns(): DashboardColumnDef<MachineSummary>[] {
  const column = columnHelperFor<MachineSummary>();

  return [
    column.accessor("code", {
      id: "code",
      header: "Machine",
      enableSorting: false,
      cell: (info) => info.getValue(),
    }),
    column.accessor("name", {
      id: "name",
      header: "Name",
      enableSorting: false,
      cell: (info) => info.getValue(),
    }),
    column.accessor("machine_type_label", {
      id: "machine_type",
      header: "Type",
      enableSorting: false,
      cell: (info) => info.getValue(),
    }),
    column.accessor("line_name", {
      id: "line_name",
      header: "Line",
      enableSorting: false,
      cell: (info) => info.getValue(),
    }),
    column.accessor("status_label", {
      id: "status",
      header: "Status",
      enableSorting: false,
      cell: (info) => info.getValue(),
    }),
    column.accessor("current_component_name", {
      id: "current_component",
      header: "Running",
      enableSorting: false,
      cell: (info) => formatText(info.getValue()),
    }),
    column.accessor("utilization_percentage", {
      id: "utilization",
      header: "Utilization",
      enableSorting: false,
      cell: (info) => formatPercentage(info.getValue()),
    }),
    column.accessor("total_downtime_minutes", {
      id: "downtime",
      header: "Downtime",
      enableSorting: false,
      cell: (info) => formatMinutes(info.getValue()),
    }),
    column.accessor("next_maintenance_date", {
      id: "next_maintenance",
      header: "Next service",
      enableSorting: false,
      cell: (info) => formatDate(info.getValue()),
    }),
  ];
}

// =============================================================================
// Maintenance
// =============================================================================

/**
 * `GET /maintenance/records` takes no sort parameter: the order depends on
 * `upcoming_only` and is decided server-side. Every column is therefore
 * unsortable rather than offering headers that silently do nothing.
 */
export function maintenanceColumns(): DashboardColumnDef<MaintenanceRecord>[] {
  const column = columnHelperFor<MaintenanceRecord>();

  return [
    column.accessor("scheduled_date", {
      id: "scheduled_date",
      header: "Scheduled",
      enableSorting: false,
      cell: (info) => formatDate(info.getValue()),
    }),
    column.accessor("machine_code", {
      id: "machine_code",
      header: "Machine",
      enableSorting: false,
      cell: (info) => info.getValue(),
    }),
    column.accessor("maintenance_type_label", {
      id: "maintenance_type",
      header: "Type",
      enableSorting: false,
      cell: (info) => info.getValue(),
    }),
    column.accessor("status_label", {
      id: "status",
      header: "Status",
      enableSorting: false,
      cell: (info) => info.getValue(),
    }),
    column.accessor("technician", {
      id: "technician",
      header: "Technician",
      enableSorting: false,
      cell: (info) => formatText(info.getValue()),
    }),
    column.accessor("downtime_minutes", {
      id: "downtime",
      header: "Downtime",
      enableSorting: false,
      cell: (info) => formatMinutes(info.getValue()),
    }),
    column.accessor("completed_at", {
      id: "completed_at",
      header: "Completed",
      enableSorting: false,
      cell: (info) => formatDateTime(info.getValue()),
    }),
    column.accessor("cost", {
      id: "cost",
      header: "Cost",
      enableSorting: false,
      cell: (info) => formatCurrency(info.getValue()),
    }),
  ];
}

// =============================================================================
// Alerts
// =============================================================================

/**
 * `GET /alerts` orders by severity then recency server-side and takes no sort
 * parameter, so these columns are unsortable too.
 */
export function alertColumns(): DashboardColumnDef<Alert>[] {
  const column = columnHelperFor<Alert>();

  return [
    column.accessor("severity_label", {
      id: "severity",
      header: "Severity",
      enableSorting: false,
      cell: (info) => info.getValue(),
    }),
    column.accessor("alert_type_label", {
      id: "alert_type",
      header: "Type",
      enableSorting: false,
      cell: (info) => info.getValue(),
    }),
    column.accessor("title", {
      id: "title",
      header: "Alert",
      enableSorting: false,
      cell: (info) => info.getValue(),
    }),
    // An alert always names at least one subject, but which one varies by type:
    // a machine for a breakdown, an inventory item for a stockout.
    column.accessor(
      (row) => row.machine_name ?? row.inventory_item_name ?? row.component_name ?? row.line_name,
      {
        id: "subject",
        header: "Subject",
        enableSorting: false,
        cell: (info) => formatText(info.getValue()),
      },
    ),
    column.accessor("status_label", {
      id: "status",
      header: "Status",
      enableSorting: false,
      cell: (info) => info.getValue(),
    }),
    column.accessor("triggered_at", {
      id: "triggered_at",
      header: "Triggered",
      enableSorting: false,
      cell: (info) => formatDateTime(info.getValue()),
    }),
    column.accessor("age_minutes", {
      id: "age",
      header: "Age",
      enableSorting: false,
      cell: (info) => formatMinutes(info.getValue()),
    }),
  ];
}
