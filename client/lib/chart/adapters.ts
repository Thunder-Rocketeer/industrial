/**
 * Chart data adapters (spec section 23).
 *
 * These map API responses into the shape a charting library wants. They are
 * deliberately dull, and the rule they follow is short:
 *
 *   **An adapter may reshape and label. It may not calculate.**
 *
 * Every percentage on this dashboard is computed by the backend, once, so that
 * two views cannot disagree (spec section 42). An adapter that quietly
 * recomputed a defect rate to "fix" a rounding difference would create a second
 * definition of the metric that nobody knows exists -- and it would be visible
 * only as two panels showing different numbers for the same day.
 *
 * What they do instead: rename fields to the axes they belong on, attach the
 * unit so a tooltip can render "9,250 units" rather than "9250", and provide a
 * text summary so a chart is not the only way to read the data (spec section
 * 19: charts must have accessible descriptions or supporting data).
 */
import { formatNumber, formatPercentage } from "@/lib/utils/format";
import type { OEETrendPoint } from "@/types/analytics";
import type { InventoryTrendPoint } from "@/types/inventory";
import type { ProductionTrendPoint } from "@/types/production";
import type { DefectSummary, DefectTrendPoint } from "@/types/quality";

/** One point on a chart, with the unit its value is measured in. */
export interface ChartPoint {
  /** Category axis value -- a date, a machine code, a defect name. */
  label: string;
  value: number;
  unit: string;
}

/** A named series of points. */
export interface ChartSeries {
  key: string;
  /** Rendered in the legend and in the text alternative. */
  label: string;
  unit: string;
  points: ChartPoint[];
}

/**
 * A chart, with everything needed to render it *and* to describe it.
 *
 * `summary` and `table` are not decoration. Spec section 19 requires charts to
 * carry a textual alternative, and spec section 45 forbids conveying meaning by
 * visuals alone -- so the adapter produces both, and Phase 6 renders the table
 * inside a details element or for screen readers only.
 */
export interface ChartData {
  series: ChartSeries[];
  /** One sentence describing what the chart shows and its range. */
  summary: string;
  /** The same numbers as rows, for an accessible table. */
  table: {
    columns: string[];
    rows: (string | number)[][];
  };
}

/** Format a number for a label. Presentation only; the value is unchanged. */
function formatValue(value: number, unit: string): string {
  return unit === "%" ? formatPercentage(value) : formatNumber(value);
}

/** Build the text summary that accompanies every chart. */
function describe(seriesLabel: string, points: ChartPoint[], unit: string): string {
  if (points.length === 0) {
    return `${seriesLabel}: no data for the selected period.`;
  }
  const values = points.map((point) => point.value);
  const first = points[0];
  const last = points[points.length - 1];
  const min = Math.min(...values);
  const max = Math.max(...values);

  return (
    `${seriesLabel} from ${first.label} to ${last.label}: ` +
    `${points.length} points, ranging from ${formatValue(min, unit)} ` +
    `to ${formatValue(max, unit)}.`
  );
}

// =============================================================================
// Production
// =============================================================================

/**
 * Production against target over time.
 *
 * Three series on one date axis. `achievement_percentage` is deliberately left
 * out: it is on a different scale, and plotting a percentage against unit
 * counts on one axis produces a chart where one series is a flat line at the
 * bottom.
 */
export function toProductionTrendChart(points: ProductionTrendPoint[]): ChartData {
  const unit = "units";
  const produced = points.map((point) => ({
    label: point.bucket_date,
    value: point.produced_quantity,
    unit,
  }));
  const target = points.map((point) => ({
    label: point.bucket_date,
    value: point.target_quantity,
    unit,
  }));
  const planned = points.map((point) => ({
    label: point.bucket_date,
    value: point.planned_quantity,
    unit,
  }));

  return {
    series: [
      { key: "produced", label: "Produced", unit, points: produced },
      { key: "target", label: "Target", unit, points: target },
      { key: "planned", label: "Planned", unit, points: planned },
    ],
    summary: describe("Production", produced, unit),
    table: {
      columns: ["Date", "Produced", "Target", "Planned", "Achievement"],
      rows: points.map((point) => [
        point.bucket_date,
        point.produced_quantity,
        point.target_quantity,
        point.planned_quantity,
        // Read from the response, not recomputed from the columns beside it.
        `${point.achievement_percentage.toFixed(1)}%`,
      ]),
    },
  };
}

// =============================================================================
// Quality
// =============================================================================

/** Daily defect rate. */
export function toDefectTrendChart(points: DefectTrendPoint[]): ChartData {
  const unit = "%";
  const rate = points.map((point) => ({
    label: point.bucket_date,
    value: point.defect_rate_percentage,
    unit,
  }));

  return {
    series: [{ key: "defect_rate", label: "Defect rate", unit, points: rate }],
    summary: describe("Defect rate", rate, unit),
    table: {
      columns: ["Date", "Inspected", "Rejected", "Defect rate"],
      rows: points.map((point) => [
        point.bucket_date,
        point.inspected_quantity,
        point.rejected_quantity,
        `${point.defect_rate_percentage.toFixed(2)}%`,
      ]),
    },
  };
}

/**
 * The defect Pareto: bars of rejected quantity, plus the cumulative line.
 *
 * `cumulative_percentage` comes straight from the response. It depends on each
 * row's position in the sorted set, so recomputing it here -- or re-sorting the
 * rows -- would silently produce a wrong curve. The order is the backend's and
 * is preserved exactly.
 */
export function toDefectParetoChart(defects: DefectSummary[]): ChartData {
  const bars = defects.map((defect) => ({
    label: defect.defect_name,
    value: defect.rejected_quantity,
    unit: "units",
  }));
  const cumulative = defects.map((defect) => ({
    label: defect.defect_name,
    value: defect.cumulative_percentage,
    unit: "%",
  }));

  const topThree = defects
    .slice(0, 3)
    .reduce((total, defect) => total + defect.share_percentage, 0);

  return {
    series: [
      { key: "rejected", label: "Rejected units", unit: "units", points: bars },
      { key: "cumulative", label: "Cumulative share", unit: "%", points: cumulative },
    ],
    summary:
      defects.length === 0
        ? "No defects recorded for the selected period."
        : `${defects.length} defect categories. The top three account for ` +
          `${topThree.toFixed(1)}% of all rejections.`,
    table: {
      columns: ["Defect", "Category", "Rejected", "Share", "Cumulative"],
      rows: defects.map((defect) => [
        defect.defect_name,
        defect.category,
        defect.rejected_quantity,
        `${defect.share_percentage.toFixed(1)}%`,
        `${defect.cumulative_percentage.toFixed(1)}%`,
      ]),
    },
  };
}

// =============================================================================
// OEE
// =============================================================================

/**
 * OEE and its three terms over time.
 *
 * All four series are plotted, because spec section 5.6 requires the components
 * to be visible separately -- an OEE line alone shows that something moved
 * without showing whether to look at breakdowns, cycle times or scrap.
 */
export function toOeeTrendChart(points: OEETrendPoint[]): ChartData {
  const unit = "%";
  const series = (
    [
      ["oee", "OEE", "oee_percentage"],
      ["availability", "Availability", "availability_percentage"],
      ["performance", "Performance", "performance_percentage"],
      ["quality", "Quality", "quality_percentage"],
    ] as const
  ).map(([key, label, field]) => ({
    key,
    label,
    unit,
    points: points.map((point) => ({
      label: point.bucket_date,
      value: point[field],
      unit,
    })),
  }));

  return {
    series,
    summary: describe("OEE", series[0].points, unit),
    table: {
      columns: ["Date", "OEE", "Availability", "Performance", "Quality"],
      rows: points.map((point) => [
        point.bucket_date,
        `${point.oee_percentage.toFixed(1)}%`,
        `${point.availability_percentage.toFixed(1)}%`,
        `${point.performance_percentage.toFixed(1)}%`,
        `${point.quality_percentage.toFixed(1)}%`,
      ]),
    },
  };
}

// =============================================================================
// Inventory
// =============================================================================

/** An item's stock level over time. */
export function toInventoryTrendChart(points: InventoryTrendPoint[], unit: string): ChartData {
  const balance = points.map((point) => ({
    // The API returns a timestamp here; the chart axis wants a day.
    label: point.bucket_date.slice(0, 10),
    value: point.balance,
    unit,
  }));

  return {
    series: [{ key: "balance", label: "Stock level", unit, points: balance }],
    summary: describe("Stock level", balance, unit),
    table: {
      columns: ["Date", `Balance (${unit})`],
      rows: balance.map((point) => [point.label, point.value]),
    },
  };
}
