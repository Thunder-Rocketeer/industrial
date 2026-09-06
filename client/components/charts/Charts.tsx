"use client";

/**
 * The application's chart set (spec section 17).
 *
 * One library — Recharts — and one set of components on top of it, so a chart
 * looks and behaves the same wherever it appears. Recharts was chosen for
 * declarative React composition, a real `ResponsiveContainer` (spec sections 17
 * and 37 both require charts to resize), and SVG output that scales without
 * blurring on high-DPI factory displays.
 *
 * Every component here takes a `ChartData` from the Phase 5 adapters. That is
 * the whole contract: the adapters map and label, these draw. Neither
 * calculates.
 */
import {
  Bar,
  CartesianGrid,
  ComposedChart,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import {
  AXIS_PROPS,
  CHART_COLORS,
  ChartFrame,
  GRID_PROPS,
  TOOLTIP_PROPS,
} from "@/components/charts/ChartFrame";
import type { ChartData } from "@/lib/chart/adapters";
import { formatNumber } from "@/lib/utils/format";

/**
 * Turn adapter output into the row-per-x-value shape Recharts expects.
 *
 * The adapters produce one array per series, which is the right shape for
 * describing a chart; Recharts wants one object per x value with a key per
 * series. This is a pure reshape -- no value is touched.
 */
function toRows(data: ChartData): Record<string, string | number>[] {
  const byLabel = new Map<string, Record<string, string | number>>();

  for (const series of data.series) {
    for (const point of series.points) {
      const row = byLabel.get(point.label) ?? { label: point.label };
      row[series.key] = point.value;
      byLabel.set(point.label, row);
    }
  }

  return [...byLabel.values()];
}

/** Shorten a long axis: "2026-01-14" is unreadable repeated thirty times. */
function shortDate(value: string): string {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value);
  if (!match) {
    return value;
  }
  const [, , month, day] = match;
  const months = [
    "Jan",
    "Feb",
    "Mar",
    "Apr",
    "May",
    "Jun",
    "Jul",
    "Aug",
    "Sep",
    "Oct",
    "Nov",
    "Dec",
  ];
  return `${day} ${months[Number(month) - 1] ?? ""}`.trim();
}

/**
 * Tooltip formatters.
 *
 * Recharts types a tooltip value as `ValueType`, a union wide enough to include
 * arrays and `undefined`, because a tooltip can be attached to any series. The
 * narrowing happens here, once, rather than being fought at four call sites.
 */
function tooltipValueFormatter(data: ChartData, unitLabel?: string) {
  return (value: unknown, name: unknown): [string, string] => {
    const label = String(name ?? "");
    const numeric = typeof value === "number" ? value : Number(value);
    if (!Number.isFinite(numeric)) {
      return ["—", label];
    }
    const unit = data.series.find((series) => series.label === label)?.unit ?? unitLabel ?? "";
    return [unit === "%" ? `${numeric}%` : `${formatNumber(numeric)} ${unit}`.trim(), label];
  };
}

const tooltipLabelFormatter = (label: unknown): string => String(label ?? "");

const LEGEND_PROPS = {
  wrapperStyle: { fontSize: "11px", paddingTop: "8px" },
  iconSize: 10,
} as const;

// =============================================================================
// Line trend
// =============================================================================

/**
 * A multi-series line chart over a date axis.
 *
 * Series after the first are dashed. That is not decoration: differentiating
 * only by colour fails WCAG 1.4.1 and makes the chart unreadable to a
 * red/green colour-vision deficiency, which is common enough on a factory floor
 * to be a certainty rather than a risk.
 */
export function LineTrendChart({
  data,
  height = 260,
  unitLabel,
  domain,
}: {
  data: ChartData;
  height?: number;
  /** Axis label, e.g. "units" or "%". */
  unitLabel?: string;
  domain?: [number | "auto", number | "auto"];
}) {
  const rows = toRows(data);

  return (
    <ChartFrame data={data} height={height}>
      <ResponsiveContainer width="100%" height="100%">
        <LineChart
          data={rows}
          accessibilityLayer={false}
          margin={{ top: 4, right: 8, bottom: 0, left: -12 }}
        >
          <CartesianGrid {...GRID_PROPS} />
          <XAxis dataKey="label" tickFormatter={shortDate} minTickGap={24} {...AXIS_PROPS} />
          <YAxis
            {...AXIS_PROPS}
            domain={domain}
            width={52}
            tickFormatter={(value: number) =>
              unitLabel === "%" ? `${value}%` : formatNumber(value)
            }
          />
          <Tooltip
            {...TOOLTIP_PROPS}
            labelFormatter={tooltipLabelFormatter}
            formatter={tooltipValueFormatter(data, unitLabel)}
          />
          {data.series.length > 1 && <Legend {...LEGEND_PROPS} />}
          {data.series.map((series, index) => (
            <Line
              key={series.key}
              type="monotone"
              dataKey={series.key}
              name={series.label}
              stroke={CHART_COLORS[index % CHART_COLORS.length]}
              strokeWidth={index === 0 ? 2 : 1.5}
              strokeDasharray={index === 0 ? undefined : index === 1 ? "5 3" : "2 2"}
              dot={false}
              activeDot={{ r: 3.5 }}
              // Only the first refresh animates; redrawing the same series
              // every thirty seconds is the "decorative animation" spec
              // section 34 warns against.
              isAnimationActive={false}
            />
          ))}
        </LineChart>
      </ResponsiveContainer>
    </ChartFrame>
  );
}

// =============================================================================
// Pareto
// =============================================================================

/**
 * Bars of quantity with the cumulative share as a line (spec section 7).
 *
 * The order and the cumulative curve both come from the backend. Re-sorting the
 * rows here, or recomputing the running total over a truncated copy, produces a
 * curve that is wrong in a way no single-row assertion would catch.
 */
export function ParetoChart({ data, height = 280 }: { data: ChartData; height?: number }) {
  const rows = toRows(data);
  const [bars, cumulative] = data.series;

  return (
    <ChartFrame data={data} height={height} emptyTitle="No defects recorded in this period">
      <ResponsiveContainer width="100%" height="100%">
        <ComposedChart
          data={rows}
          accessibilityLayer={false}
          margin={{ top: 4, right: 8, bottom: 0, left: -12 }}
        >
          <CartesianGrid {...GRID_PROPS} />
          <XAxis
            dataKey="label"
            {...AXIS_PROPS}
            interval={0}
            angle={-25}
            textAnchor="end"
            height={64}
            tickFormatter={(value: string) =>
              value.length > 14 ? `${value.slice(0, 13)}…` : value
            }
          />
          <YAxis
            yAxisId="left"
            {...AXIS_PROPS}
            width={52}
            tickFormatter={(value: number) => formatNumber(value)}
          />
          <YAxis
            yAxisId="right"
            orientation="right"
            {...AXIS_PROPS}
            width={40}
            domain={[0, 100]}
            tickFormatter={(value: number) => `${value}%`}
          />
          <Tooltip {...TOOLTIP_PROPS} formatter={tooltipValueFormatter(data)} />
          <Legend {...LEGEND_PROPS} />
          {bars && (
            <Bar
              yAxisId="left"
              dataKey={bars.key}
              name={bars.label}
              fill={CHART_COLORS[0]}
              radius={[2, 2, 0, 0]}
              maxBarSize={44}
              isAnimationActive={false}
            />
          )}
          {cumulative && (
            <Line
              yAxisId="right"
              type="monotone"
              dataKey={cumulative.key}
              name={cumulative.label}
              stroke={CHART_COLORS[1]}
              strokeWidth={2}
              dot={{ r: 2.5 }}
              isAnimationActive={false}
            />
          )}
        </ComposedChart>
      </ResponsiveContainer>
    </ChartFrame>
  );
}

// =============================================================================
// Grouped bars
// =============================================================================

/** Side-by-side bars, for comparing series across a category axis. */
export function GroupedBarChart({
  data,
  height = 260,
  unitLabel,
  horizontal = false,
}: {
  data: ChartData;
  height?: number;
  unitLabel?: string;
  horizontal?: boolean;
}) {
  const rows = toRows(data);

  return (
    <ChartFrame data={data} height={height}>
      <ResponsiveContainer width="100%" height="100%">
        <ComposedChart
          data={rows}
          accessibilityLayer={false}
          layout={horizontal ? "vertical" : "horizontal"}
          margin={{ top: 4, right: 12, bottom: 0, left: horizontal ? 8 : -12 }}
        >
          <CartesianGrid {...GRID_PROPS} vertical={horizontal} horizontal={!horizontal} />
          {horizontal ? (
            <>
              <XAxis
                type="number"
                {...AXIS_PROPS}
                tickFormatter={(value: number) =>
                  unitLabel === "%" ? `${value}%` : formatNumber(value)
                }
              />
              {/*
                `interval={0}` forces a label on every bar.

                Recharts thins category labels automatically when it thinks they
                will collide, and on a fourteen-machine fleet it dropped every
                other one — leaving half the bars anonymous. A bar chart whose
                bars cannot be identified conveys nothing, so the labels are
                mandatory and the axis is given the width to hold them.
              */}
              <YAxis type="category" dataKey="label" width={92} interval={0} {...AXIS_PROPS} />
            </>
          ) : (
            <>
              <XAxis dataKey="label" tickFormatter={shortDate} minTickGap={20} {...AXIS_PROPS} />
              <YAxis
                {...AXIS_PROPS}
                width={52}
                tickFormatter={(value: number) =>
                  unitLabel === "%" ? `${value}%` : formatNumber(value)
                }
              />
            </>
          )}
          <Tooltip {...TOOLTIP_PROPS} formatter={tooltipValueFormatter(data, unitLabel)} />
          {data.series.length > 1 && <Legend {...LEGEND_PROPS} />}
          {data.series.map((series, index) => (
            <Bar
              key={series.key}
              dataKey={series.key}
              name={series.label}
              fill={CHART_COLORS[index % CHART_COLORS.length]}
              radius={horizontal ? [0, 2, 2, 0] : [2, 2, 0, 0]}
              maxBarSize={38}
              isAnimationActive={false}
            />
          ))}
        </ComposedChart>
      </ResponsiveContainer>
    </ChartFrame>
  );
}
