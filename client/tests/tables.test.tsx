/**
 * @vitest-environment jsdom
 */

/**
 * Tables: columns, sorting, pagination and states (spec section 39).
 *
 * The table renders through the real `useServerTable` controller, so these
 * cover the whole chain from a header click to the query parameters the API
 * would receive.
 */
import { fireEvent, render, renderHook, screen, act } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { DataTable, TablePagination } from "@/components/tables/DataTable";
import { EmptyState } from "@/components/ui/States";
import { useServerTable, useServerTableState } from "@/hooks/useServerTable";
import { PRODUCTION_SORT_KEYS, productionColumns } from "@/lib/table/columns";
import { toPaginationView } from "@/lib/table/server-table";
import type { PaginatedResponse } from "@/types/api";
import type { ProductionRecord } from "@/types/production";

function record(overrides: Partial<ProductionRecord> = {}): ProductionRecord {
  return {
    id: "r1",
    record_date: "2026-01-15",
    machine_id: "m1",
    machine_code: "CNC-07",
    machine_name: "Turning centre",
    component_id: "c1",
    component_code: "BRK-01",
    component_name: "Brake disc",
    line_id: "l1",
    line_code: "L1",
    line_name: "Line 1",
    shift_id: "s1",
    shift_code: "A",
    shift_name: "Morning",
    started_at: "2026-01-15T06:00:00Z",
    ended_at: "2026-01-15T14:00:00Z",
    planned_quantity: 1000,
    produced_quantity: 950,
    accepted_quantity: 920,
    rejected_quantity: 30,
    planned_minutes: 480,
    operating_minutes: 450,
    downtime_minutes: 30,
    efficiency_percentage: 95,
    defect_rate_percentage: 3.16,
    ...overrides,
  };
}

function page(rows: ProductionRecord[], total = rows.length): PaginatedResponse<ProductionRecord> {
  return { data: rows, pagination: { page: 1, page_size: 25, total } };
}

function useTestTable(data: PaginatedResponse<ProductionRecord> | undefined) {
  const state = useServerTableState({ initialSorting: [{ id: "date", desc: true }] });
  const columns = productionColumns();
  const table = useServerTable({ columns, state, page: data });
  return { state, table };
}

describe("column definitions", () => {
  it("uses backend sort keys as the ids of sortable columns", () => {
    const columns = productionColumns();
    const sortable = columns.filter((column) => column.enableSorting !== false);

    // A column whose id is not on the API's allow-list would 422 the moment its
    // header is clicked.
    for (const column of sortable) {
      expect(PRODUCTION_SORT_KEYS).toContain(column.id as (typeof PRODUCTION_SORT_KEYS)[number]);
    }
  });

  it("marks columns the API cannot sort as unsortable", () => {
    const columns = productionColumns();
    const machine = columns.find((column) => column.id === "machine_code");
    // No control is offered that the backend would reject.
    expect(machine?.enableSorting).toBe(false);
  });
});

describe("DataTable", () => {
  it("renders a real table with a caption and column headers", () => {
    const { result } = renderHook(() => useTestTable(page([record()])));
    render(<DataTable table={result.current.table.table} caption="Production records" />);

    // A grid of divs announces nothing; the header association is the point.
    expect(screen.getByRole("table")).toBeTruthy();
    expect(screen.getByText("Production records")).toBeTruthy();
    expect(screen.getAllByRole("columnheader").length).toBeGreaterThan(5);
  });

  it("formats cells from the backend's values", () => {
    const { result } = renderHook(() => useTestTable(page([record()])));
    render(<DataTable table={result.current.table.table} caption="Production records" />);

    expect(screen.getByText("CNC-07")).toBeTruthy();
    expect(screen.getByText("950")).toBeTruthy();
    // The backend's efficiency, not one recomputed from produced/planned.
    expect(screen.getByText("95.0%")).toBeTruthy();
  });

  it("exposes sort state through aria-sort", () => {
    const { result } = renderHook(() => useTestTable(page([record()])));
    render(<DataTable table={result.current.table.table} caption="Production records" />);

    const dateHeader = screen
      .getAllByRole("columnheader")
      .find((header) => header.textContent?.includes("Date"));
    // The caret alone tells a screen reader nothing.
    expect(dateHeader?.getAttribute("aria-sort")).toBe("descending");
  });

  it("gives an unsortable header no aria-sort and no button", () => {
    const { result } = renderHook(() => useTestTable(page([record()])));
    render(<DataTable table={result.current.table.table} caption="Production records" />);

    const machineHeader = screen
      .getAllByRole("columnheader")
      .find((header) => header.textContent?.trim() === "Machine");
    expect(machineHeader?.getAttribute("aria-sort")).toBeNull();
    expect(machineHeader?.querySelector("button")).toBeNull();
  });

  it("changes the API sort parameters when a header is activated", () => {
    const { result } = renderHook(() => useTestTable(page([record()])));
    const { rerender } = render(
      <DataTable table={result.current.table.table} caption="Production records" />,
    );

    expect(result.current.state.queryFilters.sort_by).toBe("date");

    act(() => {
      const producedHeader = screen
        .getAllByRole("button")
        .find((button) => button.textContent?.includes("Produced"));
      fireEvent.click(producedHeader as HTMLElement);
    });
    rerender(<DataTable table={result.current.table.table} caption="Production records" />);

    expect(result.current.state.queryFilters.sort_by).toBe("produced");
    // A new sort reorders the whole result set, so the page number is stale.
    expect(result.current.state.queryFilters.page).toBe(1);
  });

  it("renders the empty state inside the table body", () => {
    const { result } = renderHook(() => useTestTable(page([], 0)));
    render(
      <DataTable
        table={result.current.table.table}
        caption="Production records"
        empty={<EmptyState title="No production records found" compact />}
      />,
    );

    // The headers stay, so the table does not appear to vanish.
    expect(screen.getByText("No production records found")).toBeTruthy();
    expect(screen.getAllByRole("columnheader").length).toBeGreaterThan(0);
  });

  it("makes a clickable row reachable by keyboard", () => {
    const onRowClick = vi.fn();
    const { result } = renderHook(() => useTestTable(page([record()])));
    render(
      <DataTable
        table={result.current.table.table}
        caption="Production records"
        onRowClick={onRowClick}
        rowActionLabel={(row) => `open ${row.machine_code}`}
      />,
    );

    // A click handler on the <tr> alone is unreachable without a mouse.
    const rowButton = screen.getByRole("button", { name: /open CNC-07/i });
    fireEvent.click(rowButton);
    expect(onRowClick).toHaveBeenCalledTimes(1);
  });
});

describe("pagination", () => {
  it("describes the visible range from the backend's metadata", () => {
    render(
      <TablePagination
        pagination={toPaginationView({ page: 3, page_size: 25, total: 812 })}
        onPrevious={vi.fn()}
        onNext={vi.fn()}
      />,
    );

    // Announced politely, so "Next" is confirmed for a screen-reader user.
    const status = screen.getByRole("status");
    expect(status.textContent).toBe("Showing 51-75 of 812 records");
    expect(screen.getByText("Page 3 of 33")).toBeTruthy();
  });

  it("disables Previous on the first page and Next on the last", () => {
    const { rerender } = render(
      <TablePagination
        pagination={toPaginationView({ page: 1, page_size: 25, total: 812 })}
        onPrevious={vi.fn()}
        onNext={vi.fn()}
      />,
    );
    expect(screen.getByRole("button", { name: /previous/i }).hasAttribute("disabled")).toBe(true);

    rerender(
      <TablePagination
        pagination={toPaginationView({ page: 33, page_size: 25, total: 812 })}
        onPrevious={vi.fn()}
        onNext={vi.fn()}
      />,
    );
    expect(screen.getByRole("button", { name: /next/i }).hasAttribute("disabled")).toBe(true);
  });

  it("renders nothing when there are no records", () => {
    const { container } = render(
      <TablePagination
        pagination={toPaginationView({ page: 1, page_size: 25, total: 0 })}
        onPrevious={vi.fn()}
        onNext={vi.fn()}
      />,
    );
    // The empty state already explains the situation.
    expect(container.firstChild).toBeNull();
  });

  it("advances the page through the controller", () => {
    const { result } = renderHook(() => useTestTable(page([record()], 812)));
    expect(result.current.state.queryFilters.page).toBe(1);

    act(() => result.current.state.nextPage());
    expect(result.current.state.queryFilters.page).toBe(2);

    act(() => result.current.state.resetPage());
    expect(result.current.state.queryFilters.page).toBe(1);
  });

  it("caps the page size at the backend's maximum", () => {
    const { result } = renderHook(() => useTestTable(page([record()], 812)));
    act(() => result.current.state.setPageSize(5000));
    expect(result.current.state.queryFilters.page_size).toBe(100);
  });
});
