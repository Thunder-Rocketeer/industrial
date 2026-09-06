/**
 * The TanStack Table feature set used across the dashboard (spec section 24).
 *
 * TanStack Table v9 is opt-in: a table gets only the features listed here, and
 * the type of every column definition depends on that list. Declaring it once
 * means every table shares one column-definition type and one bundle cost.
 *
 * Two features, and no client-side row models:
 *
 *   - `rowPaginationFeature` holds page state, but the rows come from the
 *     backend one page at a time. There is no `paginatedRowModel`, because
 *     slicing rows in the browser requires having all of them there first --
 *     which spec section 24 forbids ("do not implement large tables by loading
 *     every database record"). With three months of production history that is
 *     tens of thousands of rows to download, parse and hold in memory to show
 *     twenty-five of them.
 *
 *   - `rowSortingFeature` holds sort state, but sorting also happens in
 *     PostgreSQL against an allow-listed column. Sorting in the browser would
 *     only reorder the current page, so clicking "sort by quantity" would sort
 *     twenty-five rows out of forty thousand -- an answer that looks right and
 *     is wrong.
 *
 * Both therefore run in manual mode; see `server-table.ts` for the bridge.
 * Column filtering is not included: filters are inputs bound to API query
 * parameters, not a table feature.
 */
import {
  createColumnHelper,
  rowPaginationFeature,
  rowSortingFeature,
  tableFeatures,
} from "@tanstack/react-table";
import type { ColumnDef, RowData } from "@tanstack/react-table";

export const dashboardTableFeatures = tableFeatures({
  rowPaginationFeature,
  rowSortingFeature,
});

export type DashboardTableFeatures = typeof dashboardTableFeatures;

/** A column definition for a dashboard table of `TRow`. */
export type DashboardColumnDef<TRow extends RowData> = ColumnDef<
  DashboardTableFeatures,
  TRow,
  // The value type varies per column; the table only needs it to be present.
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  any
>;

/**
 * A typed column helper for one row type.
 *
 * Used instead of hand-writing `ColumnDef` objects so accessor keys are checked
 * against the row type: a typo in a field name is a compile error rather than a
 * column of blanks.
 */
export function columnHelperFor<TRow extends RowData>() {
  return createColumnHelper<DashboardTableFeatures, TRow>();
}
