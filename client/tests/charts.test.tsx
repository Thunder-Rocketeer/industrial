/**
 * @vitest-environment jsdom
 */

/**
 * Charts: adapter data rendering, empty states, and the text alternative
 * (spec section 39).
 *
 * jsdom has no layout, so Recharts' `ResponsiveContainer` measures zero and
 * draws nothing. That is fine, and it isolates what actually matters here: the
 * accessible equivalent. WCAG 1.1.1 treats a chart as a non-text element, so
 * the summary and the data table are the parts a test can and should hold onto.
 */
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ParetoChart } from "@/components/charts/Charts";
import { ChartFrame } from "@/components/charts/ChartFrame";
import { toDefectParetoChart, toProductionTrendChart } from "@/lib/chart/adapters";
import type { ProductionTrendPoint } from "@/types/production";
import type { DefectSummary } from "@/types/quality";

const points: ProductionTrendPoint[] = [
  {
    bucket_date: "2026-01-01",
    planned_quantity: 1000,
    produced_quantity: 900,
    accepted_quantity: 880,
    rejected_quantity: 20,
    target_quantity: 950,
    achievement_percentage: 94.7,
  },
  {
    bucket_date: "2026-01-02",
    planned_quantity: 1000,
    produced_quantity: 1100,
    accepted_quantity: 1080,
    rejected_quantity: 20,
    target_quantity: 950,
    achievement_percentage: 115.8,
  },
];

const defects: DefectSummary[] = [
  {
    defect_id: "d1",
    defect_code: "D1",
    defect_name: "Surface finish",
    category: "Finishing",
    default_severity: "MAJOR",
    rejected_quantity: 500,
    occurrence_count: 40,
    share_percentage: 62.5,
    cumulative_percentage: 62.5,
  },
];

describe("chart frame", () => {
  it("carries a text summary as the figure caption", () => {
    const data = toProductionTrendChart(points);
    render(
      <ChartFrame data={data}>
        <div />
      </ChartFrame>,
    );

    const figure = screen.getByRole("figure");
    // The equivalent for a non-text element (WCAG 1.1.1).
    expect(figure.textContent).toContain("Production from 2026-01-01 to 2026-01-02");
  });

  it("offers the underlying numbers as a real table", () => {
    const data = toProductionTrendChart(points);
    render(
      <ChartFrame data={data}>
        <div />
      </ChartFrame>,
    );

    // A sentence summarises; only the table gives the value for a given day.
    expect(screen.getByText("View data as a table")).toBeTruthy();
    const table = screen.getByRole("table");
    expect(table.textContent).toContain("Produced");
    expect(table.textContent).toContain("900");
    // The backend's achievement, not one recomputed from the columns beside it.
    expect(table.textContent).toContain("94.7%");
  });

  it("hides the plotted SVG from assistive technology", () => {
    const data = toProductionTrendChart(points);
    const { container } = render(
      <ChartFrame data={data}>
        <div data-testid="plot" />
      </ChartFrame>,
    );

    // Recharts emits hundreds of nodes; exposing them is an unusable stream of
    // numbers. The summary and the table are the accessible equivalent.
    const plotWrapper = container.querySelector('[aria-hidden="true"]');
    expect(plotWrapper?.querySelector('[data-testid="plot"]')).toBeTruthy();
  });

  it("renders an empty state instead of blank axes", () => {
    const data = toProductionTrendChart([]);
    render(
      <ChartFrame data={data} emptyTitle="No production in this period">
        <div data-testid="plot" />
      </ChartFrame>,
    );

    expect(screen.getByText("No production in this period")).toBeTruthy();
    expect(screen.queryByTestId("plot")).toBeNull();
  });

  it("keeps the backend's Pareto ordering and cumulative share", () => {
    const data = toDefectParetoChart(defects);
    render(
      <ChartFrame data={data}>
        <div />
      </ChartFrame>,
    );

    const table = screen.getByRole("table");
    expect(table.textContent).toContain("Surface finish");
    // `cumulative_percentage` depends on row position; recomputing it over a
    // truncated copy produces a curve that is wrong and looks fine.
    expect(table.textContent).toContain("62.5%");
  });

  it("says so when a Pareto has no defects", () => {
    // Through the real chart component, which supplies the domain-specific
    // empty wording rather than the frame's generic default.
    render(<ParetoChart data={toDefectParetoChart([])} />);
    expect(screen.getByText("No defects recorded in this period")).toBeTruthy();
  });
});
