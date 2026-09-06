"use client";

/**
 * Server-driven table state (spec section 24).
 *
 * Two hooks, because of the order things have to happen in a single render:
 * the query needs the page number *before* it runs, and the table needs the
 * rows *after* it returns. One hook cannot supply both without handing the
 * table a render-old page.
 *
 *   1. `useServerTableState` owns page and sort state and produces the API
 *      query parameters that state implies.
 *   2. `useServerTable` takes those parameters, the response, and the column
 *      definitions, and produces the table instance.
 *
 * ```tsx
 * const columns = useMemo(() => productionColumns(), []);
 * const tableState = useServerTableState({ initialSorting: [{ id: "date", desc: true }] });
 * const records = useProductionRecords({ ...filters, ...tableState.queryFilters });
 * const table = useServerTable({ columns, state: tableState, page: records.data });
 * ```
 *
 * Neither hook fetches: the query hook stays the only place a request is made,
 * so one controller works for every list endpoint. Neither computes a metric or
 * interprets a value either -- they convert state to parameters and response
 * metadata to control state, and nothing else.
 */
import { useTable } from "@tanstack/react-table";
import type { PaginationState, ReactTable, RowData, SortingState } from "@tanstack/react-table";
import { useCallback, useEffect, useMemo, useState } from "react";

import { PAGINATION } from "@/lib/constants/cache";
import {
  type DashboardColumnDef,
  type DashboardTableFeatures,
  dashboardTableFeatures,
} from "@/lib/table/features";
import {
  type ServerPaginationView,
  clampedPageIndex,
  toPaginationView,
  toQueryFilters,
} from "@/lib/table/server-table";
import type { PaginatedResponse, PaginationParams, SortParams } from "@/types/api";

// =============================================================================
// State
// =============================================================================

export interface UseServerTableStateOptions {
  pageSize?: number;
  /**
   * Initial sort. `id` must be a sort key the endpoint accepts -- see the
   * `*_SORT_KEYS` constants in `lib/table/columns.ts`.
   */
  initialSorting?: SortingState;
}

export interface ServerTableState {
  pagination: PaginationState;
  sorting: SortingState;
  /** Spread into the filters passed to the query hook. */
  queryFilters: PaginationParams & SortParams;
  setPagination: (next: PaginationState) => void;
  setSorting: (next: SortingState) => void;
  setPageIndex: (pageIndex: number) => void;
  setPageSize: (pageSize: number) => void;
  nextPage: () => void;
  previousPage: () => void;
  /** Return to page 1. Call when a filter outside the table changes. */
  resetPage: () => void;
}

export function useServerTableState({
  pageSize = PAGINATION.defaultPageSize,
  initialSorting = [],
}: UseServerTableStateOptions = {}): ServerTableState {
  const [pagination, setPaginationState] = useState<PaginationState>({
    pageIndex: 0,
    pageSize,
  });
  const [sorting, setSortingState] = useState<SortingState>(initialSorting);

  const setPagination = useCallback((next: PaginationState) => {
    setPaginationState(next);
  }, []);

  const setSorting = useCallback((next: SortingState) => {
    setSortingState(next);
    // A different sort order reorders the whole result set, not just the page
    // on screen, so the old page number is meaningless: staying on page 7 would
    // show the seventh page of a set whose top the user has not seen.
    setPaginationState((current) => ({ ...current, pageIndex: 0 }));
  }, []);

  const setPageIndex = useCallback((pageIndex: number) => {
    setPaginationState((current) => ({
      ...current,
      pageIndex: Math.max(0, pageIndex),
    }));
  }, []);

  const setPageSize = useCallback((nextPageSize: number) => {
    setPaginationState({
      // Row 51 sits on a different page at 25 per page than at 100, so there is
      // no honest way to preserve the position. Page 1 is the predictable one.
      pageIndex: 0,
      pageSize: Math.min(Math.max(1, nextPageSize), PAGINATION.maxPageSize),
    });
  }, []);

  const nextPage = useCallback(() => {
    setPaginationState((current) => ({
      ...current,
      pageIndex: current.pageIndex + 1,
    }));
  }, []);

  const previousPage = useCallback(() => {
    setPaginationState((current) => ({
      ...current,
      pageIndex: Math.max(0, current.pageIndex - 1),
    }));
  }, []);

  const resetPage = useCallback(() => setPageIndex(0), [setPageIndex]);

  const queryFilters = useMemo(
    () => toQueryFilters({ pagination, sorting }),
    [pagination, sorting],
  );

  return {
    pagination,
    sorting,
    queryFilters,
    setPagination,
    setSorting,
    setPageIndex,
    setPageSize,
    nextPage,
    previousPage,
    resetPage,
  };
}

// =============================================================================
// Table instance
// =============================================================================

export interface UseServerTableOptions<TRow extends RowData> {
  columns: DashboardColumnDef<TRow>[];
  state: ServerTableState;
  /** The current page of rows, or undefined while loading. */
  page?: PaginatedResponse<TRow>;
}

export interface ServerTable<TRow extends RowData> {
  table: ReactTable<DashboardTableFeatures, TRow>;
  /** Everything the pagination controls need to render. */
  pagination: ServerPaginationView;
}

export function useServerTable<TRow extends RowData>({
  columns,
  state,
  page,
}: UseServerTableOptions<TRow>): ServerTable<TRow> {
  const rows = useMemo(() => page?.data ?? [], [page]);
  const view = useMemo(() => toPaginationView(page?.pagination), [page]);

  const { pagination, sorting, setPagination, setSorting } = state;

  /**
   * A filter change can leave the table on a page that no longer exists, which
   * the API answers with an empty list -- indistinguishable from "no matching
   * records". Snapping back to the last real page happens here, once, rather
   * than having to be remembered at every call site that owns a filter.
   */
  useEffect(() => {
    const corrected = clampedPageIndex(pagination, page?.pagination);
    if (corrected !== null) {
      setPagination({ ...pagination, pageIndex: corrected });
    }
  }, [page, pagination, setPagination]);

  const table = useTable({
    features: dashboardTableFeatures,
    columns,
    data: rows,
    state: { pagination, sorting },
    onPaginationChange: (updater) => {
      setPagination(typeof updater === "function" ? updater(pagination) : updater);
    },
    onSortingChange: (updater) => {
      setSorting(typeof updater === "function" ? updater(sorting) : updater);
    },
    // The backend paginates and sorts; the browser only reflects the result.
    manualPagination: true,
    manualSorting: true,
    // Passed through from the response so the controls know the real extent of
    // the data, not just the size of the page in hand.
    rowCount: view.rowCount,
  });

  return { table, pagination: view };
}
