/**
 * Chart adapters and display formatting (spec sections 23 and 31).
 *
 * The invariant worth testing here is a negative one: an adapter must pass a
 * backend value through unchanged. A recomputed percentage would still render,
 * still look reasonable, and disagree with the KPI card above it only on the
 * rows where the difference matters -- so the assertion is that the number in
 * the chart is the number in the response.
 */
import { describe, expect, it } from "vitest";

import {
  toDefectParetoChart,
  toDefectTrendChart,
  toOeeTrendChart,
  toProductionTrendChart,
} from "@/lib/chart/adapters";
import {
  EMPTY_VALUE,
  formatDate,
  formatDateTime,
  formatMinutes,
  formatNumber,
  formatPercentage,
} from "@/lib/utils/format";
import type { OEETrendPoint } from "@/types/analytics";
import type { ProductionTrendPoint } from "@/types/production";
import type { DefectSummary, DefectTrendPoint } from "@/types/quality";

const productionPoints: ProductionTrendPoint[] = [
  {
    bucket_date: "2026-01-01",
    planned_quantity: 1_000,
    produced_quantity: 900,
    accepted_quantity: 880,
    rejected_quantity: 20,
    target_quantity: 950,
    achievement_percentage: 94.7,
  },
  {
    bucket_date: "2026-01-02",
    planned_quantity: 1_000,
    produced_quantity: 1_100,
    accepted_quantity: 1_080,
    rejected_quantity: 20,
    target_quantity: 950,
    achievement_percentage: 115.8,
  },
];

describe("production trend adapter", () => {
  it("maps each series onto the date axis without altering values", () => {
    const chart = toProductionTrendChart(productionPoints);

    const produced = chart.series.find((series) => series.key === "produced");
    expect(produced?.points.map((point) => point.value)).toEqual([900, 1_100]);
    expect(produced?.points.map((point) => point.label)).toEqual(["2026-01-01", "2026-01-02"]);
  });

  it("reads achievement from the response rather than recomputing it", () => {
    const chart = toProductionTrendChart(productionPoints);

    // 900/950 is 94.7%, and the backend says 94.7%. The point is that the
    // adapter did not divide: it copied.
    expect(chart.table.rows[0]).toContain("94.7%");
    expect(chart.table.rows[1]).toContain("115.8%");
  });

  it("carries the unit on every point", () => {
    const chart = toProductionTrendChart(productionPoints);
    for (const series of chart.series) {
      expect(series.points.every((point) => point.unit === "units")).toBe(true);
    }
  });

  it("produces a text alternative for the chart", () => {
    // Spec section 19: a chart is not the only way to read the data.
    const chart = toProductionTrendChart(productionPoints);
    expect(chart.summary).toContain("2026-01-01");
    expect(chart.summary).toContain("2026-01-02");
    expect(chart.table.columns).toContain("Produced");
  });

  it("handles an empty series without throwing", () => {
    const chart = toProductionTrendChart([]);
    expect(chart.series.every((series) => series.points.length === 0)).toBe(true);
    expect(chart.summary).toContain("no data");
  });
});

describe("defect adapters", () => {
  const trend: DefectTrendPoint[] = [
    {
      bucket_date: "2026-01-01",
      inspected_quantity: 1_000,
      rejected_quantity: 33,
      defect_rate_percentage: 3.3,
    },
  ];

  const defects: DefectSummary[] = [
    {
      defect_id: "00000000-0000-4000-8000-000000000001",
      defect_code: "D1",
      defect_name: "Surface finish",
      category: "Finishing",
      default_severity: "MAJOR",
      rejected_quantity: 500,
      occurrence_count: 40,
      share_percentage: 50,
      cumulative_percentage: 50,
    },
    {
      defect_id: "00000000-0000-4000-8000-000000000002",
      defect_code: "D2",
      defect_name: "Dimensional",
      category: "Machining",
      default_severity: "CRITICAL",
      rejected_quantity: 300,
      occurrence_count: 25,
      share_percentage: 30,
      cumulative_percentage: 80,
    },
  ];

  it("passes the defect rate through untouched", () => {
    const chart = toDefectTrendChart(trend);
    expect(chart.series[0].points[0].value).toBe(3.3);
  });

  it("keeps the backend's Pareto order and cumulative curve", () => {
    const chart = toDefectParetoChart(defects);

    // `cumulative_percentage` depends on a row's position in the sorted set.
    // Re-sorting here, or recomputing the running total, produces a curve that
    // is subtly and invisibly wrong.
    expect(chart.series[0].points.map((point) => point.label)).toEqual([
      "Surface finish",
      "Dimensional",
    ]);
    expect(chart.series[1].points.map((point) => point.value)).toEqual([50, 80]);
  });

  it("says so when there are no defects", () => {
    expect(toDefectParetoChart([]).summary).toContain("No defects");
  });
});

describe("OEE adapter", () => {
  const points: OEETrendPoint[] = [
    {
      bucket_date: "2026-01-01",
      availability_percentage: 85,
      performance_percentage: 90,
      quality_percentage: 96.7,
      oee_percentage: 74,
      performance_uncapped_percentage: 90,
    },
  ];

  it("plots OEE alongside its three components", () => {
    const chart = toOeeTrendChart(points);
    expect(chart.series.map((series) => series.key)).toEqual([
      "oee",
      "availability",
      "performance",
      "quality",
    ]);
  });

  it("does not multiply the components to derive OEE", () => {
    // 0.85 * 0.90 * 0.967 is 73.98, which rounds to 74.0 -- close enough that a
    // recomputation would pass a loose assertion. The value must be the
    // backend's, so the exact figure it sent is what appears.
    expect(toOeeTrendChart(points).series[0].points[0].value).toBe(74);
  });
});

describe("formatting", () => {
  it("renders a null as an em dash, not as 0 or 'null'", () => {
    // A missing value and a zero are different facts. "0 units" where the
    // backend sent null states something that was never measured.
    expect(formatNumber(null)).toBe(EMPTY_VALUE);
    expect(formatPercentage(undefined)).toBe(EMPTY_VALUE);
    expect(formatDate(null)).toBe(EMPTY_VALUE);
    expect(formatDateTime(null)).toBe(EMPTY_VALUE);
    expect(formatMinutes(null)).toBe(EMPTY_VALUE);
  });

  it("keeps zero, which is a measurement", () => {
    expect(formatNumber(0)).toBe("0");
    expect(formatPercentage(0)).toBe("0.0%");
    expect(formatMinutes(0)).toBe("0 min");
  });

  it("does not shift an ISO date by a day", () => {
    // Parsed as UTC midnight, `new Date("2026-01-05")` renders as 4 January
    // anywhere behind UTC -- an off-by-one on every date in every table.
    expect(formatDate("2026-01-05")).toBe("Jan 05, 2026");
  });

  it("renders timestamps in UTC and says so", () => {
    // Two people in different offices comparing a shift start must be reading
    // the same clock.
    expect(formatDateTime("2026-01-05T06:30:00Z")).toContain("UTC");
    expect(formatDateTime("2026-01-05T06:30:00Z")).toContain("06:30");
  });

  it("formats durations past an hour", () => {
    expect(formatMinutes(45)).toBe("45 min");
    expect(formatMinutes(120)).toBe("2 h");
    expect(formatMinutes(135)).toBe("2 h 15 min");
  });

  it("does not round a percentage away from what the backend sent", () => {
    expect(formatPercentage(94.75, 2)).toBe("94.75%");
  });
});
