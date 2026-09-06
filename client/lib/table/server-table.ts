/**
 * The bridge between the backend's pagination/sorting contract and TanStack
 * Table's state (spec section 24).
 *
 * Two conventions have to meet here and they disagree on one detail: TanStack
 * Table counts pages from 0, the API counts from 1. Every off-by-one bug in a
 * server-driven table lives in that gap, so the conversion happens in exactly
 * these two functions and nowhere else.
 *
 * These are pure functions with no React and no network access, which is what
 * makes the conversion testable on its own.
 */
import type { PaginationState, SortingState } from "@tanstack/react-table";

import { PAGINATION } from "@/lib/constants/cache";
import { formatNumber } from "@/lib/utils/format";
import type { PaginationMeta, PaginationParams, SortParams } from "@/types/api";

/** The parts of table state that decide what the server is asked for. */
export interface ServerTableQueryState {
  pagination: PaginationState;
  sorting: SortingState;
}

/**
 * Convert table state into API query parameters.
 *
 * `sort_by` is only sent when a column is actually sorted; sending an empty
 * string would make the backend reject the request against its allow-list.
 * Only the first sort column is sent, because the API accepts one -- multi-sort
 * is therefore not offered in the UI rather than being silently truncated.
 */
export function toQueryFilters(state: ServerTableQueryState): PaginationParams & SortParams {
  const params: PaginationParams & SortParams = {
    // 0-indexed in the table, 1-indexed over the wire.
    page: state.pagination.pageIndex + 1,
    page_size: Math.min(state.pagination.pageSize, PAGINATION.maxPageSize),
  };

  const [primarySort] = state.sorting;
  if (primarySort) {
    params.sort_by = primarySort.id;
    params.sort_dir = primarySort.desc ? "desc" : "asc";
  }

  return params;
}

/**
 * What the table needs from the response envelope in order to render controls.
 *
 * The backend's `total` is preserved and passed through as `rowCount` rather
 * than being inferred from the length of the current page -- spec section 24:
 * "preserve backend pagination metadata". Without it the table cannot know that
 * page 3 of 812 exists, and "Next" would be disabled on every full page.
 */
export interface ServerPaginationView {
  rowCount: number;
  pageCount: number;
  /** 1-based, for "Page 3 of 812". */
  page: number;
  pageSize: number;
  /** 1-based index of the first row on this page; 0 when there are no rows. */
  firstRowOnPage: number;
  /** 1-based index of the last row on this page; 0 when there are no rows. */
  lastRowOnPage: number;
  hasPreviousPage: boolean;
  hasNextPage: boolean;
  /** "Showing 51-75 of 812 records" -- spec section 26. */
  label: string;
}

/**
 * Derive everything the pagination controls display from the backend metadata.
 *
 * `meta` may be undefined while the first page is loading. Rather than making
 * callers branch, an empty view is returned so the controls render disabled
 * instead of disappearing and shifting the layout when data arrives.
 */
export function toPaginationView(meta: PaginationMeta | undefined): ServerPaginationView {
  if (!meta || meta.page_size <= 0) {
    return {
      rowCount: 0,
      pageCount: 0,
      page: 1,
      pageSize: PAGINATION.defaultPageSize,
      firstRowOnPage: 0,
      lastRowOnPage: 0,
      hasPreviousPage: false,
      hasNextPage: false,
      label: "No records",
    };
  }

  const pageCount = Math.ceil(meta.total / meta.page_size);
  const firstRowOnPage = meta.total === 0 ? 0 : (meta.page - 1) * meta.page_size + 1;
  const lastRowOnPage = Math.min(meta.page * meta.page_size, meta.total);

  return {
    rowCount: meta.total,
    pageCount,
    page: meta.page,
    pageSize: meta.page_size,
    firstRowOnPage,
    lastRowOnPage,
    hasPreviousPage: meta.page > 1,
    hasNextPage: meta.page < pageCount,
    label:
      meta.total === 0
        ? "No records"
        : `Showing ${formatNumber(firstRowOnPage)}-${formatNumber(lastRowOnPage)} ` +
          `of ${formatNumber(meta.total)} records`,
  };
}

/**
 * Clamp a page index that has fallen off the end of the result set.
 *
 * Narrowing a filter while on page 40 leaves the table asking for a page that
 * no longer exists, and the backend answers with an empty list -- which looks
 * exactly like "no matching records" even though there are plenty. Callers
 * apply this after a response to send the user back to the last real page.
 * Returns null when the current index is fine, so it can guard a setState.
 */
export function clampedPageIndex(
  state: PaginationState,
  meta: PaginationMeta | undefined,
): number | null {
  if (!meta || meta.total === 0 || meta.page_size <= 0) {
    return null;
  }
  const lastPageIndex = Math.max(0, Math.ceil(meta.total / meta.page_size) - 1);
  return state.pageIndex > lastPageIndex ? lastPageIndex : null;
}
