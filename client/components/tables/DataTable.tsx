"use client";

/**
 * The application's table renderer (spec section 19).
 *
 * Renders a TanStack Table instance built by Phase 5's `useServerTable`. All
 * pagination and sorting is server-driven: one page of rows is in the DOM at a
 * time, never a whole result set (spec section 19).
 *
 * Accessibility (spec section 18, WCAG 1.3.1 and 4.1.2):
 *
 *  - A real `<table>` with `<th scope="col">`. A grid of divs announces nothing
 *    to a screen reader; the header association is the entire point of a table.
 *  - A `<caption>`, visually hidden, naming what the table contains.
 *  - Sortable headers are `<button>`s inside the `<th>`, carrying
 *    `aria-sort` on the cell. The button text states the next action -- "Sort
 *    by Produced, ascending" -- rather than leaving a bare caret.
 *  - Non-sortable headers render as plain text, so no control is offered that
 *    the API would reject.
 *
 * Horizontal overflow is contained: the wrapper scrolls, the page does not
 * (spec section 37).
 */
import { flexRender } from "@tanstack/react-table";
import type { RowData } from "@tanstack/react-table";
import type { ReactNode } from "react";

import { Button } from "@/components/ui/Button";
import { Icon } from "@/components/ui/Icon";
import type { ServerTable } from "@/hooks/useServerTable";
import { cn } from "@/lib/utils/cn";

export interface DataTableProps<TRow extends RowData> {
  table: ServerTable<TRow>["table"];
  /** Visually hidden caption naming the table's contents. */
  caption: string;
  /** Rendered in the tbody when there are no rows. */
  empty?: ReactNode;
  /** Called with the row's original data when a row is activated. */
  onRowClick?: (row: TRow) => void;
  /** Accessible description of what clicking a row does. */
  rowActionLabel?: (row: TRow) => string;
}

export function DataTable<TRow extends RowData>({
  table,
  caption,
  empty,
  onRowClick,
  rowActionLabel,
}: DataTableProps<TRow>) {
  const rows = table.getRowModel().rows;

  return (
    <div className="w-full overflow-x-auto">
      <table className="w-full border-collapse text-sm">
        <caption className="sr-only">{caption}</caption>
        <thead>
          {table.getHeaderGroups().map((headerGroup) => (
            <tr key={headerGroup.id}>
              {headerGroup.headers.map((header) => {
                const canSort = header.column.getCanSort();
                const sorted = header.column.getIsSorted();

                return (
                  <th
                    key={header.id}
                    scope="col"
                    // `aria-sort` is what tells a screen reader the column is
                    // sorted and which way. The caret alone says nothing.
                    aria-sort={
                      !canSort
                        ? undefined
                        : sorted === "asc"
                          ? "ascending"
                          : sorted === "desc"
                            ? "descending"
                            : "none"
                    }
                    className="border-border-base bg-surface-sunken/60 text-subtle border-b px-3 py-2 text-left text-xs font-medium whitespace-nowrap"
                  >
                    {canSort ? (
                      <button
                        type="button"
                        onClick={header.column.getToggleSortingHandler()}
                        className="hover:text-foreground -mx-1 flex items-center gap-1 rounded px-1 py-0.5 transition-colors"
                      >
                        <span>
                          {flexRender(header.column.columnDef.header, header.getContext())}
                        </span>
                        <Icon
                          name={
                            sorted === "asc"
                              ? "mdi:arrow-up"
                              : sorted === "desc"
                                ? "mdi:arrow-down"
                                : "mdi:unfold-more-horizontal"
                          }
                          size={13}
                          className={sorted ? "text-accent" : "opacity-40"}
                        />
                        <span className="sr-only">
                          {sorted === "asc"
                            ? ", sorted ascending. Activate to sort descending."
                            : sorted === "desc"
                              ? ", sorted descending. Activate to remove sorting."
                              : ". Activate to sort ascending."}
                        </span>
                      </button>
                    ) : (
                      flexRender(header.column.columnDef.header, header.getContext())
                    )}
                  </th>
                );
              })}
            </tr>
          ))}
        </thead>

        <tbody>
          {rows.length === 0 ? (
            <tr>
              <td colSpan={table.getAllLeafColumns().length} className="px-3 py-0">
                {empty}
              </td>
            </tr>
          ) : (
            rows.map((row) => {
              const interactive = Boolean(onRowClick);
              return (
                <tr
                  key={row.id}
                  className={cn(
                    "border-border-base/60 border-b last:border-b-0",
                    interactive && "hover:bg-surface-sunken/60 cursor-pointer",
                  )}
                  onClick={interactive ? () => onRowClick?.(row.original) : undefined}
                >
                  {row.getAllCells().map((cell, cellIndex) => (
                    <td
                      key={cell.id}
                      className="text-foreground px-3 py-2.5 align-middle whitespace-nowrap"
                    >
                      {/* The first cell of a clickable row carries the actual
                          keyboard-reachable control. Putting a click handler
                          only on the <tr> would make the row unreachable
                          without a mouse (WCAG 2.1.1). */}
                      {interactive && cellIndex === 0 ? (
                        <button
                          type="button"
                          onClick={(event) => {
                            event.stopPropagation();
                            onRowClick?.(row.original);
                          }}
                          className="hover:text-accent text-left font-medium underline-offset-2 hover:underline"
                        >
                          {flexRender(cell.column.columnDef.cell, cell.getContext())}
                          {rowActionLabel && (
                            <span className="sr-only">, {rowActionLabel(row.original)}</span>
                          )}
                        </button>
                      ) : (
                        flexRender(cell.column.columnDef.cell, cell.getContext())
                      )}
                    </td>
                  ))}
                </tr>
              );
            })
          )}
        </tbody>
      </table>
    </div>
  );
}

/**
 * Pagination controls driven by the backend's metadata (spec section 19).
 *
 * The record range is announced in a live region: after "Next", a screen-reader
 * user otherwise gets no confirmation that anything changed, because the table
 * body swaps silently.
 */
export function TablePagination({
  pagination,
  onPrevious,
  onNext,
  onPageSizeChange,
  pageSize,
  disabled = false,
}: {
  pagination: {
    label: string;
    page: number;
    pageCount: number;
    hasPreviousPage: boolean;
    hasNextPage: boolean;
    rowCount: number;
  };
  onPrevious: () => void;
  onNext: () => void;
  onPageSizeChange?: (size: number) => void;
  pageSize?: number;
  disabled?: boolean;
}) {
  if (pagination.rowCount === 0) {
    return null;
  }

  return (
    <div className="border-border-base flex flex-wrap items-center justify-between gap-3 border-t px-3 py-2.5">
      <p className="text-subtle text-xs" role="status" aria-live="polite">
        {pagination.label}
      </p>

      <div className="flex items-center gap-2">
        {onPageSizeChange && pageSize !== undefined && (
          <label className="text-subtle flex items-center gap-1.5 text-xs">
            <span className="hidden sm:inline">Rows</span>
            <select
              value={pageSize}
              onChange={(event) => onPageSizeChange(Number(event.target.value))}
              className="border-border-strong bg-surface text-foreground h-7 rounded border px-1.5 text-xs"
            >
              {[25, 50, 100].map((size) => (
                <option key={size} value={size}>
                  {size}
                </option>
              ))}
            </select>
          </label>
        )}

        <span className="text-subtle text-xs whitespace-nowrap">
          Page {pagination.page} of {Math.max(pagination.pageCount, 1)}
        </span>

        <div className="flex gap-1">
          <Button
            size="sm"
            icon="mdi:chevron-left"
            onClick={onPrevious}
            disabled={disabled || !pagination.hasPreviousPage}
          >
            <span className="sr-only sm:not-sr-only">Previous</span>
          </Button>
          <Button size="sm" onClick={onNext} disabled={disabled || !pagination.hasNextPage}>
            <span className="sr-only sm:not-sr-only">Next</span>
            <Icon name="mdi:chevron-right" size={14} />
          </Button>
        </div>
      </div>
    </div>
  );
}
