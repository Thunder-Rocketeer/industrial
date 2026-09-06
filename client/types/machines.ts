/**
 * Machine response models, mirroring `app/schemas/machines.py`.
 */
import type {
  IsoDate,
  IsoDateTime,
  MachineStatus,
  MachineType,
  MaintenanceStatus,
  MaintenanceType,
  Uuid,
} from "@/types/common";

/** A machine as it appears on the machines board. */
export interface MachineSummary {
  id: Uuid;
  code: string;
  name: string;
  machine_type: MachineType;
  machine_type_label: string;

  line_id: Uuid;
  line_code: string;
  line_name: string;

  status: MachineStatus;
  status_label: string;

  current_component_id: Uuid | null;
  current_component_name: string | null;

  utilization_percentage: number;
  total_downtime_minutes: number;

  commissioned_date: IsoDate;
  last_maintenance_date: IsoDate | null;
  next_maintenance_date: IsoDate | null;
  /** Negative when overdue. */
  days_until_maintenance: number | null;
  /** True within the attention window, or already overdue. */
  maintenance_due: boolean;
}

/** A machine's production over the requested window, with its OEE terms. */
export interface MachineProductionStats {
  produced_quantity: number;
  accepted_quantity: number;
  rejected_quantity: number;
  planned_quantity: number;
  operating_minutes: number;
  planned_minutes: number;
  downtime_minutes: number;
  run_count: number;

  availability_percentage: number;
  performance_percentage: number;
  quality_percentage: number;
  oee_percentage: number;
  defect_rate_percentage: number;
}

/** One maintenance job. */
export interface MaintenanceRecord {
  id: Uuid;
  machine_id: Uuid;
  machine_code: string;
  machine_name: string;
  maintenance_type: MaintenanceType;
  maintenance_type_label: string;
  status: MaintenanceStatus;
  status_label: string;
  scheduled_date: IsoDate;
  started_at: IsoDateTime | null;
  completed_at: IsoDateTime | null;
  downtime_minutes: number;
  technician: string;
  description: string;
  cost: number | null;
  /** Scheduled in the past and not yet completed or cancelled. */
  is_overdue: boolean;
}

/** A single machine with statistics and maintenance history. */
export interface MachineDetail extends MachineSummary {
  production: MachineProductionStats;
  recent_maintenance: MaintenanceRecord[];
  upcoming_maintenance: MaintenanceRecord[];
}

/** How many machines are in one operational state. */
export interface MachineStatusCount {
  status: MachineStatus;
  status_label: string;
  count: number;
}

/** Fleet-level machine availability. */
export interface MachineFleetSummary {
  total_machines: number;
  running_count: number;
  idle_count: number;
  maintenance_count: number;
  offline_count: number;

  /** Only RUNNING machines count as available; an idle machine is not producing. */
  availability_percentage: number;
  average_utilization_percentage: number;
  maintenance_due_count: number;
  status_breakdown: MachineStatusCount[];
}

/** Filters accepted by the machine list. Unpaginated: the fleet is small. */
export interface MachineFilters {
  status?: MachineStatus;
  line_id?: Uuid;
}

/** Window for a machine's production statistics. */
export interface MachineDetailFilters {
  start_date?: IsoDate;
  end_date?: IsoDate;
}
