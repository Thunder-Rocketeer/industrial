"use client";

/**
 * Shared chart chrome (spec sections 17 and 18).
 *
 * Every chart in the application is wrapped in this, which supplies the two
 * things a chart needs to be accessible and which are almost always missing:
 *
 *   1. **A text summary.** WCAG 1.1.1 treats a chart as a non-text element, so
 *      it needs an equivalent. The summary comes from the Phase 5 adapters,
 *      which build it from the same numbers the chart plots -- so it cannot
 *      drift from what is drawn.
 *
 *   2. **The underlying data as a real table**, in a `<details>` element. This
 *      is the honest fallback: a sentence summarises, but only the table lets
 *      someone read the actual value for the 14th. It is collapsed by default
 *      so it costs sighted users nothing, and it is reachable by keyboard and
 *      by screen reader on every chart.
 *
 * The SVG itself is `aria-hidden`. Recharts emits hundreds of path and text
 * nodes; exposing them produces an unusable stream of numbers, and the summary
 * plus the table are the accessible equivalent.
 */
import type { ReactNode } from "react";

import { EmptyState } from "@/components/ui/States";
import type { ChartData } from "@/lib/chart/adapters";

export function ChartFrame({
  data,
  height = 260,
  children,
  emptyTitle = "No data for this period",
  emptyMessage,
  tableCaption,
}: {
  data: ChartData;
  height?: number;
  /** The Recharts tree. Rendered inside a responsive container. */
  children: ReactNode;
  emptyTitle?: string;
  emptyMessage?: string;
  tableCaption?: string;
}) {
  const isEmpty = data.series.every((series) => series.points.length === 0);

  if (isEmpty) {
    return (
      <EmptyState title={emptyTitle} message={emptyMessage} icon="mdi:chart-line-variant" compact />
    );
  }

  return (
    <figure className="m-0">
      {/* Visually hidden, but the first thing a screen reader meets. */}
      <figcaption className="sr-only">{data.summary}</figcaption>

      <div aria-hidden="true" style={{ height }} className="w-full">
        {children}
      </div>

      <details className="group mt-2">
        <summary className="text-subtle hover:text-foreground cursor-pointer text-xs select-none">
          View data as a table
        </summary>
        <div className="mt-2 max-h-64 overflow-auto">
          <table className="w-full border-collapse text-xs">
            {tableCaption && (
              <caption className="text-subtle pb-2 text-left text-xs">{tableCaption}</caption>
            )}
            <thead>
              <tr>
                {data.table.columns.map((column) => (
                  <th
                    key={column}
                    scope="col"
                    className="border-border-base text-subtle border-b px-2 py-1.5 text-left font-medium whitespace-nowrap"
                  >
                    {column}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {data.table.rows.map((row, rowIndex) => (
                <tr key={rowIndex}>
                  {row.map((cell, cellIndex) => (
                    <td
                      key={cellIndex}
                      className="border-border-base/60 text-muted border-b px-2 py-1.5 whitespace-nowrap"
                    >
                      {cell}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </details>
    </figure>
  );
}

/** Chart colours, read from the CSS tokens so dark mode is handled centrally. */
export const CHART_COLORS = [
  "var(--chart-1)",
  "var(--chart-2)",
  "var(--chart-3)",
  "var(--chart-4)",
  "var(--chart-5)",
] as const;

/** Shared axis and grid styling, so no two charts drift apart. */
export const AXIS_PROPS = {
  stroke: "var(--chart-axis)",
  fontSize: 11,
  tickLine: false,
  axisLine: false,
} as const;

export const GRID_PROPS = {
  stroke: "var(--chart-grid)",
  strokeDasharray: "3 3",
  vertical: false,
} as const;

/**
 * Tooltip styling.
 *
 * Recharts renders tooltips inline, so the theme tokens are applied here rather
 * than through a class.
 */
export const TOOLTIP_PROPS = {
  contentStyle: {
    background: "var(--surface-raised)",
    border: "1px solid var(--border)",
    borderRadius: "6px",
    fontSize: "12px",
    color: "var(--foreground)",
    boxShadow: "0 4px 12px rgb(0 0 0 / 0.08)",
  },
  labelStyle: { color: "var(--muted)", marginBottom: 4, fontSize: "11px" },
  itemStyle: { padding: "1px 0" },
  cursor: { stroke: "var(--border-strong)", strokeWidth: 1 },
} as const;
