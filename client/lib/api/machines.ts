/**
 * Machine API.
 */
import { get } from "@/lib/api/client";
import { buildParams } from "@/lib/api/params";
import type { ApiEnvelope } from "@/types/api";
import type { Uuid } from "@/types/common";
import type {
  MachineDetail,
  MachineDetailFilters,
  MachineFilters,
  MachineFleetSummary,
  MachineSummary,
} from "@/types/machines";

/**
 * The machine fleet.
 *
 * Unpaginated, matching the backend: the fleet is a dozen or so machines and
 * the board shows all of them at once, so paginating would add a round trip and
 * a control nobody would use.
 */
export async function fetchMachines(filters: MachineFilters = {}): Promise<MachineSummary[]> {
  const response = await get<ApiEnvelope<MachineSummary[]>>("/machines", {
    params: buildParams(filters),
  });
  return response.data;
}

/** Fleet counts and overall availability. */
export async function fetchMachineSummary(): Promise<MachineFleetSummary> {
  const response = await get<ApiEnvelope<MachineFleetSummary>>("/machines/summary");
  return response.data;
}

/** One machine with its statistics, OEE terms and maintenance history. */
export async function fetchMachine(
  machineId: Uuid,
  filters: MachineDetailFilters = {},
): Promise<MachineDetail> {
  const response = await get<ApiEnvelope<MachineDetail>>(`/machines/${machineId}`, {
    params: buildParams(filters),
  });
  return response.data;
}
