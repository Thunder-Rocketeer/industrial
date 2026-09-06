"use client";

/**
 * Options for the filter dropdowns (spec section 27).
 *
 * The API has no dedicated reference endpoints, so the option lists come from
 * the grouping endpoints that already exist: `/production/by-component` returns
 * every component that produced anything in the period, with its id, code and
 * name. That is exactly the right list to filter by -- it contains the values
 * that can actually match, so the dropdown cannot offer a choice that yields an
 * empty table.
 *
 * The lists are cached at the `reference` tier (30 minutes). They change when a
 * line is reconfigured, which is not something that happens between two page
 * views.
 */
import { useMemo } from "react";

import { useMachines } from "@/hooks/queries/useMachines";
import { useProductionByDimension } from "@/hooks/queries/useProduction";
import { useDefectBreakdown } from "@/hooks/queries/useQuality";
import type { FilterOption } from "@/components/filters/Filters";

/** How many options a dropdown will list before it stops being usable. */
const MAX_OPTIONS = 100;

export interface FilterOptionsResult {
  options: FilterOption[];
  isLoading: boolean;
}

/** Machines, as `CODE — Name`. Sorted by code so the list is scannable. */
export function useMachineOptions(): FilterOptionsResult {
  const machines = useMachines();

  const options = useMemo(() => {
    const rows = machines.data ?? [];
    return [...rows]
      .sort((a, b) => a.code.localeCompare(b.code))
      .map((machine) => ({
        value: machine.id,
        label: `${machine.code} — ${machine.name}`,
      }));
  }, [machines.data]);

  return { options, isLoading: machines.isLoading };
}

/**
 * Options from a production grouping.
 *
 * The grouping is filtered by the same date range as the page, so the choices
 * narrow to what is relevant. `limit` is capped: a select with five hundred
 * entries is not a usable control, and the grouping endpoints cap at 100 too.
 */
function useProductionDimensionOptions(
  dimension: "component" | "shift" | "line",
  filters: { start_date?: string; end_date?: string },
): FilterOptionsResult {
  const query = useProductionByDimension(dimension, { ...filters, limit: MAX_OPTIONS });

  const options = useMemo(() => {
    const rows = query.data ?? [];
    return [...rows]
      .sort((a, b) => a.key_name.localeCompare(b.key_name))
      .map((row) => ({ value: row.key_id, label: row.key_name }));
  }, [query.data]);

  return { options, isLoading: query.isLoading };
}

export function useComponentOptions(filters: {
  start_date?: string;
  end_date?: string;
}): FilterOptionsResult {
  return useProductionDimensionOptions("component", filters);
}

export function useShiftOptions(filters: {
  start_date?: string;
  end_date?: string;
}): FilterOptionsResult {
  return useProductionDimensionOptions("shift", filters);
}

export function useLineOptions(filters: {
  start_date?: string;
  end_date?: string;
}): FilterOptionsResult {
  return useProductionDimensionOptions("line", filters);
}

/**
 * Defect types that actually occurred in the period.
 *
 * Sourced from the Pareto breakdown rather than a reference list, so the
 * dropdown offers only defects that produced a rejection in this range. The
 * backend caps this endpoint at 50 -- a Pareto with more bars is not a Pareto --
 * which is comfortably more than a usable select anyway.
 */
export function useDefectOptions(filters: {
  start_date?: string;
  end_date?: string;
}): FilterOptionsResult {
  const query = useDefectBreakdown({ ...filters, limit: 50 });

  const options = useMemo(() => {
    const rows = query.data ?? [];
    return [...rows]
      .sort((a, b) => a.defect_name.localeCompare(b.defect_name))
      .map((row) => ({ value: row.defect_id, label: row.defect_name }));
  }, [query.data]);

  return { options, isLoading: query.isLoading };
}
