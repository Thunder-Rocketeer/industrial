"use client";

/**
 * The KPI card (spec sections 4 and 5.1).
 *
 * Every value it renders was computed by the backend and arrives on
 * `DashboardKpi`: value, unit, context, status, and the trend against the
 * previous period. Nothing here divides one field by another -- spec section 4
 * and Phase 5's rule both hold, and a second implementation of "achievement"
 * would disagree with the production page on exactly the days that matter.
 *
 * Three details that are easy to get wrong:
 *
 *   1. **Status is never colour alone** (spec section 4, WCAG 1.4.1). The card
 *      renders the word -- Healthy, Warning, Critical -- next to the tint.
 *
 *   2. **Direction is never an arrow alone.** The trend shows an arrow *and*
 *      the signed percentage *and* the comparison in words, because an arrow
 *      is invisible to a screen reader and ambiguous in print.
 *
 *   3. **A null trend is not zero.** `change_percentage` is nullable on purpose
 *      (Phase 5): there may be no previous period to compare against. Rendering
 *      "0.0% vs yesterday" in that case states something false, so the card
 *      says the comparison is unavailable instead.
 */
import { Card } from "@/components/ui/Card";
import { Icon } from "@/components/ui/Icon";
import { StatusBadge, kpiStatusTone } from "@/components/ui/Status";
import { formatNumber, formatPercentage } from "@/lib/utils/format";
import type { DashboardKpi, KpiTrend } from "@/types/dashboard";

/** Format the value with its unit, without changing it. */
function renderValue(value: number, unit: string): string {
  if (unit === "%") {
    return formatPercentage(value);
  }
  return formatNumber(value);
}

const DIRECTION_ICON: Record<KpiTrend["direction"], string> = {
  up: "mdi:arrow-top-right",
  down: "mdi:arrow-bottom-right",
  flat: "mdi:arrow-right",
  unknown: "mdi:help-circle-outline",
};

export function KpiCard({ kpi }: { kpi: DashboardKpi }) {
  const tone = kpiStatusTone(kpi.status);
  const trend = kpi.trend;
  const hasComparison = trend.change_percentage !== null;

  /*
   * A single sentence for assistive technology.
   *
   * The visual card is four small pieces of text in a deliberate spatial
   * arrangement; read linearly by a screen reader that becomes a stream of
   * fragments. This composes them into one readable statement and hides the
   * pieces, so the card is as quick to take in aurally as visually.
   */
  const description = [
    `${kpi.label}: ${renderValue(kpi.value, kpi.unit)}${kpi.unit && kpi.unit !== "%" ? ` ${kpi.unit}` : ""}.`,
    kpi.context_label ? `${kpi.context_label}.` : "",
    `Status: ${kpi.status_label}.`,
    hasComparison
      ? `Trend: ${trend.direction === "up" ? "up" : trend.direction === "down" ? "down" : "unchanged"} ${formatPercentage(Math.abs(trend.change_percentage as number))} ${trend.comparison_label}.`
      : `No ${trend.comparison_label} comparison available.`,
  ]
    .filter(Boolean)
    .join(" ");

  return (
    <Card className="flex flex-col p-4">
      <p className="sr-only">{description}</p>

      <div aria-hidden="true" className="flex min-w-0 flex-col">
        <div className="flex items-start justify-between gap-2">
          <h3 className="text-subtle truncate text-xs font-medium">{kpi.label}</h3>
          <StatusBadge tone={tone} size="sm">
            {kpi.status_label}
          </StatusBadge>
        </div>

        <p className="text-foreground mt-2 text-2xl leading-tight font-semibold tracking-tight">
          {renderValue(kpi.value, kpi.unit)}
          {kpi.unit && kpi.unit !== "%" && (
            <span className="text-subtle ml-1 text-sm font-normal">{kpi.unit}</span>
          )}
        </p>

        {kpi.context_label && (
          <p className="text-muted mt-1 truncate text-xs">{kpi.context_label}</p>
        )}

        <div className="mt-2.5 flex items-center gap-1.5 text-xs">
          {hasComparison ? (
            <>
              <Icon
                name={DIRECTION_ICON[trend.direction]}
                size={14}
                className={
                  trend.direction === "up"
                    ? "text-good"
                    : trend.direction === "down"
                      ? "text-critical"
                      : "text-subtle"
                }
              />
              <span className="text-foreground font-medium">
                {(trend.change_percentage as number) > 0 ? "+" : ""}
                {formatPercentage(trend.change_percentage as number)}
              </span>
              <span className="text-subtle truncate">{trend.comparison_label}</span>
            </>
          ) : (
            <span className="text-subtle truncate">No {trend.comparison_label} comparison</span>
          )}
        </div>
      </div>
    </Card>
  );
}

/**
 * A KPI card built from values that are not part of the backend's `kpis` array.
 *
 * Used on the module pages, where the figures come from that module's own
 * summary endpoint. It still only *displays*: every number passed in was
 * computed server-side.
 */
export function StatCard({
  label,
  value,
  unit,
  context,
  tone,
  statusLabel,
}: {
  label: string;
  value: string;
  unit?: string;
  context?: string;
  tone?: "good" | "warn" | "critical" | "neutral" | "info";
  statusLabel?: string;
}) {
  return (
    <Card className="flex flex-col p-4">
      <div className="flex items-start justify-between gap-2">
        <h3 className="text-subtle truncate text-xs font-medium">{label}</h3>
        {tone && statusLabel && (
          <StatusBadge tone={tone} size="sm">
            {statusLabel}
          </StatusBadge>
        )}
      </div>
      <p className="text-foreground mt-2 text-2xl leading-tight font-semibold tracking-tight">
        {value}
        {unit && <span className="text-subtle ml-1 text-sm font-normal">{unit}</span>}
      </p>
      {context && <p className="text-muted mt-1 text-xs">{context}</p>}
    </Card>
  );
}
