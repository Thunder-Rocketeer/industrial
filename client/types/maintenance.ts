/**
 * Maintenance filters.
 *
 * `MaintenanceRecord` itself lives in `types/machines.ts`, mirroring the
 * backend where the schema sits alongside the machine models. A maintenance job
 * is always a job on a machine, and duplicating the type would create two
 * definitions to keep in step.
 */
import type { MaintenanceStatus, PaginationFilters, Uuid } from "@/types/common";

export type { MaintenanceRecord } from "@/types/machines";

/** Filters accepted by the maintenance list. */
export interface MaintenanceFilters extends PaginationFilters {
  status?: MaintenanceStatus;
  machine_id?: Uuid;
  /**
   * Return only scheduled and in-progress work.
   *
   * Also flips the ordering: history comes back newest-first, upcoming work
   * soonest-first, so the next job is at the top rather than buried under
   * everything that already happened.
   */
  upcoming_only?: boolean;
}
