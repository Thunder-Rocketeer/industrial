/**
 * @vitest-environment jsdom
 */

/**
 * Filter controls and URL synchronization (spec section 39).
 *
 * Two properties matter here, and both are security-adjacent as much as they
 * are UX:
 *
 *  - Only allow-listed keys are read from or written to the URL, so a crafted
 *    link cannot inject a query parameter the page never meant to send.
 *  - Clearing a filter removes the key rather than leaving `?machine_id=`,
 *    which the backend rejects as a malformed UUID.
 */
import { fireEvent, render, renderHook, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { DateRangeFilter, FilterBar, SelectFilter } from "@/components/filters/Filters";

const replace = vi.fn();
let currentSearch = "";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace, push: vi.fn(), prefetch: vi.fn() }),
  usePathname: () => "/production",
  useSearchParams: () => new URLSearchParams(currentSearch),
}));

beforeEach(() => {
  replace.mockClear();
  currentSearch = "";
});

afterEach(() => {
  vi.clearAllMocks();
});

// Imported after the mock so the module picks it up.
const { defaultDateRange, useUrlFilters } = await import("@/hooks/useUrlFilters");

const KEYS = ["start_date", "end_date", "machine_id"] as const;

describe("useUrlFilters", () => {
  it("reads allow-listed keys from the query string", () => {
    currentSearch = "start_date=2026-01-01&machine_id=m1";
    const { result } = renderHook(() => useUrlFilters(KEYS));

    expect(result.current.filters).toEqual({
      start_date: "2026-01-01",
      machine_id: "m1",
    });
  });

  it("ignores parameters that are not allow-listed", () => {
    // A crafted link cannot smuggle an extra parameter into the API request.
    currentSearch = "machine_id=m1&role=admin&limit=99999";
    const { result } = renderHook(() => useUrlFilters(KEYS));

    expect(result.current.filters).toEqual({ machine_id: "m1" });
    expect(result.current.filters).not.toHaveProperty("role");
  });

  it("treats an empty value as absent", () => {
    currentSearch = "machine_id=&start_date=2026-01-01";
    const { result } = renderHook(() => useUrlFilters(KEYS));

    expect(result.current.filters).toEqual({ start_date: "2026-01-01" });
  });

  it("writes a filter into the URL", () => {
    const { result } = renderHook(() => useUrlFilters(KEYS));
    result.current.setFilter("machine_id", "m1");

    // `replace`, not `push`: adjusting a filter should not stack history.
    expect(replace).toHaveBeenCalledWith("/production?machine_id=m1", { scroll: false });
  });

  it("removes the key when a filter is cleared", () => {
    currentSearch = "machine_id=m1&start_date=2026-01-01";
    const { result } = renderHook(() => useUrlFilters(KEYS));
    result.current.setFilter("machine_id", undefined);

    // `?machine_id=` would be a 422 against a UUID field.
    expect(replace).toHaveBeenCalledWith("/production?start_date=2026-01-01", { scroll: false });
  });

  it("sets several keys in one navigation", () => {
    const { result } = renderHook(() => useUrlFilters(KEYS));
    result.current.setFilters({ start_date: "2026-01-01", end_date: "2026-01-31" });

    expect(replace).toHaveBeenCalledTimes(1);
    const [url] = replace.mock.calls[0];
    expect(url).toContain("start_date=2026-01-01");
    expect(url).toContain("end_date=2026-01-31");
  });

  it("refuses to write a key outside the allow-list", () => {
    const { result } = renderHook(() => useUrlFilters(KEYS));
    // @ts-expect-error -- deliberately passing a key the page does not own.
    result.current.setFilter("role", "admin");

    expect(replace).not.toHaveBeenCalled();
  });

  it("resets only its own keys", () => {
    currentSearch = "machine_id=m1&tab=summary";
    const { result } = renderHook(() => useUrlFilters(KEYS));
    result.current.reset();

    // `tab` belongs to something else and is left alone.
    expect(replace).toHaveBeenCalledWith("/production?tab=summary", { scroll: false });
  });

  it("counts active filters for the Clear control", () => {
    currentSearch = "machine_id=m1&start_date=2026-01-01";
    const { result } = renderHook(() => useUrlFilters(KEYS));

    expect(result.current.activeCount).toBe(2);
    expect(result.current.hasActiveFilters).toBe(true);
  });
});

describe("defaultDateRange", () => {
  it("returns an inclusive range of the requested length, in UTC", () => {
    const range = defaultDateRange(30);
    expect(range.start_date).toMatch(/^\d{4}-\d{2}-\d{2}$/);
    expect(range.end_date).toMatch(/^\d{4}-\d{2}-\d{2}$/);

    const days =
      (Date.parse(range.end_date) - Date.parse(range.start_date)) / (24 * 60 * 60 * 1000);
    expect(days).toBe(29);
  });
});

describe("filter controls", () => {
  it("labels a select and commits the chosen value", () => {
    const onChange = vi.fn();
    render(
      <SelectFilter
        label="Machine"
        value={undefined}
        options={[{ value: "m1", label: "CNC-01" }]}
        onChange={onChange}
      />,
    );

    // A real <label>, not a placeholder (WCAG 3.3.2).
    const select = screen.getByLabelText("Machine");
    fireEvent.change(select, { target: { value: "m1" } });
    expect(onChange).toHaveBeenCalledWith("m1");
  });

  it("passes undefined when the select returns to All", () => {
    const onChange = vi.fn();
    render(
      <SelectFilter
        label="Machine"
        value="m1"
        options={[{ value: "m1", label: "CNC-01" }]}
        onChange={onChange}
      />,
    );

    fireEvent.change(screen.getByLabelText("Machine"), { target: { value: "" } });
    expect(onChange).toHaveBeenCalledWith(undefined);
  });

  it("cross-bounds the date inputs so an end cannot precede a start", () => {
    render(<DateRangeFilter startDate="2026-01-01" endDate="2026-01-31" onChange={vi.fn()} />);

    // Preventing the invalid state beats reporting it (WCAG 3.3.3).
    expect(screen.getByLabelText("From").getAttribute("max")).toBe("2026-01-31");
    expect(screen.getByLabelText("To").getAttribute("min")).toBe("2026-01-01");
  });

  it("is a labelled search landmark", () => {
    render(
      <FilterBar>
        <div />
      </FilterBar>,
    );
    expect(screen.getByRole("search", { name: "Filters" })).toBeTruthy();
  });

  it("offers Clear only when a filter is set", () => {
    const { rerender } = render(
      <FilterBar onReset={vi.fn()} activeCount={0}>
        <div />
      </FilterBar>,
    );
    expect(screen.queryByRole("button", { name: /clear/i })).toBeNull();

    rerender(
      <FilterBar onReset={vi.fn()} activeCount={2}>
        <div />
      </FilterBar>,
    );
    expect(screen.getByRole("button", { name: /clear 2 filters/i })).toBeTruthy();
  });
});

describe("debounced search", () => {
  it("issues one change after typing stops", async () => {
    const { SearchFilter } = await import("@/components/filters/Filters");
    const onChange = vi.fn();

    render(<SearchFilter label="Search" value={undefined} onChange={onChange} delayMs={20} />);

    const input = screen.getByLabelText("Search");
    fireEvent.change(input, { target: { value: "b" } });
    fireEvent.change(input, { target: { value: "br" } });
    fireEvent.change(input, { target: { value: "brake" } });

    // Ten keystrokes must not be ten requests (spec section 27).
    await waitFor(() => expect(onChange).toHaveBeenCalledTimes(1));
    expect(onChange).toHaveBeenCalledWith("brake");
  });
});
