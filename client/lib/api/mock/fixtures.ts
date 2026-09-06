/**
 * Development fixtures (spec section 30).
 *
 * OBVIOUSLY FAKE, ON PURPOSE.
 *
 * Every machine here is named "MOCK-...", every component is a "Mock ...", and
 * the numbers are round. That is a design decision, not laziness: fixture data
 * that looks plausible is the kind that ends up in a screenshot, a status
 * report, or a decision. Anyone glancing at a screen served from this file can
 * tell within a second that it is not real production data.
 *
 * These exist so the frontend can be developed while the backend is
 * unavailable. They are not a test double -- tests build their own data inline,
 * next to the assertion that uses it.
 */
import type { Alert, AlertSummary } from "@/types/alerts";
import type { OEEComponents } from "@/types/analytics";
import type { DashboardSummary } from "@/types/dashboard";
import type { InventorySummary } from "@/types/inventory";
import type { MachineFleetSummary, MachineSummary } from "@/types/machines";
import type { ProductionSummary } from "@/types/production";
import type { QualitySummary } from "@/types/quality";

/** Fixed dates, so fixture output never changes between runs. */
const MOCK_START = "2026-01-01";
const MOCK_END = "2026-01-15";

export const mockProductionSummary: ProductionSummary = {
  start_date: MOCK_START,
  end_date: MOCK_END,
  total_planned: 100_000,
  total_produced: 90_000,
  total_accepted: 87_000,
  total_rejected: 3_000,
  target_quantity: 95_000,
  achievement_percentage: 94.7,
  efficiency_percentage: 90,
  defect_rate_percentage: 3.3,
  total_planned_minutes: 20_000,
  total_operating_minutes: 18_000,
  total_downtime_minutes: 2_000,
  record_count: 500,
  has_data: true,
};

export const mockQualitySummary: QualitySummary = {
  start_date: MOCK_START,
  end_date: MOCK_END,
  total_inspected: 90_000,
  total_passed: 87_000,
  total_rejected: 3_000,
  total_first_pass: 86_500,
  total_rework: 500,
  defect_rate_percentage: 3.3,
  first_pass_yield_percentage: 96.1,
  quality_rate_percentage: 96.7,
  distinct_defect_types: 8,
  record_count: 500,
  has_data: true,
};

export const mockOee: OEEComponents = {
  availability_percentage: 85,
  performance_percentage: 90,
  quality_percentage: 96.7,
  oee_percentage: 74,
  performance_uncapped_percentage: 90,
};

export const mockMachines: MachineSummary[] = [
  {
    id: "00000000-0000-4000-8000-000000000001",
    code: "MOCK-CNC-01",
    name: "Mock CNC Lathe",
    machine_type: "CNC_TURNING_CENTER",
    machine_type_label: "CNC turning centre",
    line_id: "00000000-0000-4000-8000-0000000000a1",
    line_code: "MOCK-L1",
    line_name: "Mock Line 1",
    status: "RUNNING",
    status_label: "Running",
    current_component_id: "00000000-0000-4000-8000-0000000000c1",
    current_component_name: "Mock Bracket",
    utilization_percentage: 90,
    total_downtime_minutes: 120,
    commissioned_date: "2020-01-01",
    last_maintenance_date: "2025-12-01",
    next_maintenance_date: "2026-02-01",
    days_until_maintenance: 17,
    maintenance_due: false,
  },
  {
    id: "00000000-0000-4000-8000-000000000002",
    code: "MOCK-GRD-02",
    name: "Mock Grinder",
    machine_type: "GRINDING_MACHINE",
    machine_type_label: "Grinding machine",
    line_id: "00000000-0000-4000-8000-0000000000a1",
    line_code: "MOCK-L1",
    line_name: "Mock Line 1",
    status: "OFFLINE",
    status_label: "Offline",
    current_component_id: null,
    current_component_name: null,
    utilization_percentage: 40,
    total_downtime_minutes: 600,
    commissioned_date: "2019-06-01",
    last_maintenance_date: "2025-11-01",
    next_maintenance_date: "2026-01-10",
    days_until_maintenance: -5,
    maintenance_due: true,
  },
];

export const mockMachineFleetSummary: MachineFleetSummary = {
  total_machines: 2,
  running_count: 1,
  idle_count: 0,
  maintenance_count: 0,
  offline_count: 1,
  availability_percentage: 50,
  average_utilization_percentage: 65,
  maintenance_due_count: 1,
  status_breakdown: [
    { status: "RUNNING", status_label: "Running", count: 1 },
    { status: "OFFLINE", status_label: "Offline", count: 1 },
  ],
};

export const mockInventorySummary: InventorySummary = {
  total_items: 10,
  healthy_count: 8,
  low_count: 1,
  critical_count: 1,
  overstocked_count: 0,
  health_percentage: 80,
  items_requiring_attention: 2,
  total_stock_value: 250_000,
  status_breakdown: [
    { status: "HEALTHY", status_label: "Healthy", count: 8 },
    { status: "LOW", status_label: "Low", count: 1 },
    { status: "CRITICAL", status_label: "Critical", count: 1 },
  ],
};

export const mockAlerts: Alert[] = [
  {
    id: "00000000-0000-4000-8000-0000000000f1",
    alert_type: "MACHINE_OFFLINE",
    alert_type_label: "Machine offline",
    severity: "CRITICAL",
    severity_label: "Critical",
    status: "OPEN",
    status_label: "Open",
    title: "MOCK-GRD-02 is offline",
    description: "This is mock alert data. The grinder has stopped reporting.",
    machine_id: "00000000-0000-4000-8000-000000000002",
    machine_code: "MOCK-GRD-02",
    machine_name: "Mock Grinder",
    component_id: null,
    component_name: null,
    inventory_item_id: null,
    inventory_item_name: null,
    line_id: "00000000-0000-4000-8000-0000000000a1",
    line_name: "Mock Line 1",
    triggered_at: `${MOCK_END}T06:00:00Z`,
    acknowledged_at: null,
    resolved_at: null,
    age_minutes: 120,
  },
];

export const mockAlertSummary: AlertSummary = {
  total_open: 1,
  critical_count: 1,
  warning_count: 0,
  info_count: 0,
  acknowledged_count: 0,
  severity_breakdown: [{ severity: "CRITICAL", severity_label: "Critical", count: 1 }],
};

export const mockDashboardSummary: DashboardSummary = {
  generated_at: `${MOCK_END}T08:00:00Z`,
  business_date: MOCK_END,
  kpis: [
    {
      key: "oee",
      label: "OEE (mock)",
      value: 74,
      unit: "%",
      context_label: "Mock data — not a real measurement",
      status: "warning",
      status_label: "Below target",
      trend: {
        change_percentage: 1.5,
        direction: "up",
        comparison_label: "vs previous mock period",
      },
    },
  ],
  production: mockProductionSummary,
  quality: mockQualitySummary,
  inventory: mockInventorySummary,
  machines: mockMachineFleetSummary,
  oee: mockOee,
  alerts: mockAlertSummary,
  recent_alerts: mockAlerts,
  cache_hit: false,
};
