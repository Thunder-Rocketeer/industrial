"use client";

/**
 * Compact operational visualizations (spec sections 6, 8, 9 and 11).
 *
 * These are bars and counts rather than charts, which is a deliberate choice:
 * for "how does OEE break down" and "planned versus actual" a chart library
 * adds an axis, a legend and 200px of height to communicate three numbers. A
 * labelled bar reads faster, resizes trivially, and carries its value as text.
 *
 * On arithmetic: a bar's *width* is computed here, because a width is
 * presentation. No metric is. Every percentage rendered as text came from the
 * backend, and where a proportion is needed for a width it is derived from the
 * quantities the API already sent, never re-derived into a displayed figure.
 */
import { Icon } from "@/components/ui/Icon";
import { StatusBadge, type Tone } from "@/components/ui/Status";
import { cn } from "@/lib/utils/cn";
import { formatNumber, formatPercentage } from "@/lib/utils/format";

const TONE_BAR: Record<Tone, string> = {
  good: "bg-good",
  warn: "bg-warn",
  critical: "bg-critical",
  neutral: "bg-neutral-status",
  info: "bg-accent",
};

/**
 * A labelled percentage bar.
 *
 * The number is always rendered as text beside the bar. The bar is the summary;
 * the text is the value (WCAG 1.4.1).
 */
export function MetricBar({
  label,
  percentage,
  tone = "info",
  hint,
  emphasis = false,
}: {
  label: string;
  percentage: number;
  tone?: Tone;
  hint?: string;
  emphasis?: boolean;
}) {
  // Clamped for the bar only. A performance figure above 100 is real and is
  // rendered as text; it just cannot draw past the end of its track.
  const width = Math.max(0, Math.min(100, percentage));

  return (
    <div>
      <div className="flex items-baseline justify-between gap-2">
        <span
          className={cn(
            "truncate text-xs",
            emphasis ? "text-foreground font-medium" : "text-muted",
          )}
        >
          {label}
        </span>
        <span
          className={cn(
            "shrink-0 tabular-nums",
            emphasis
              ? "text-foreground text-sm font-semibold"
              : "text-foreground text-xs font-medium",
          )}
        >
          {formatPercentage(percentage)}
        </span>
      </div>
      <div
        className="bg-surface-sunken mt-1.5 h-1.5 w-full overflow-hidden rounded-full"
        role="img"
        aria-label={`${label}: ${formatPercentage(percentage)}`}
      >
        <div className={cn("h-full rounded-full", TONE_BAR[tone])} style={{ width: `${width}%` }} />
      </div>
      {hint && <p className="text-subtle mt-1 text-[11px]">{hint}</p>}
    </div>
  );
}

/**
 * OEE with its three factors (spec section 11).
 *
 * Spec section 11 asks that OEE not be "a mysterious single number" -- the user
 * must be able to see which factor is dragging it down. So the three terms are
 * always shown beside it, each with its own bar, and the lowest is called out
 * in words. That last part is what turns a display into something actionable:
 * "OEE 74%" prompts a question, "Availability is the lowest factor at 85%"
 * points at breakdowns.
 *
 * All four values come from `services/kpi.py`. Nothing here multiplies them.
 */
export function OeeBreakdown({
  oee,
  availability,
  performance,
  quality,
  performanceUncapped,
  compact = false,
}: {
  oee: number;
  availability: number;
  performance: number;
  quality: number;
  /** Above 100 means bad reference cycle-time data, not a fast machine. */
  performanceUncapped?: number;
  compact?: boolean;
}) {
  const factors = [
    { key: "availability", label: "Availability", value: availability },
    { key: "performance", label: "Performance", value: performance },
    { key: "quality", label: "Quality", value: quality },
  ];

  // Which factor to look at first. A comparison for wording, not a new metric.
  const weakest = factors.reduce((lowest, factor) =>
    factor.value < lowest.value ? factor : lowest,
  );

  const tone: Tone = oee >= 75 ? "good" : oee >= 60 ? "warn" : "critical";
  const toneLabel = oee >= 75 ? "Healthy" : oee >= 60 ? "Warning" : "Critical";

  const cycleTimeWarning = performanceUncapped !== undefined && performanceUncapped > 100.5;

  return (
    <div className={cn("flex flex-col gap-4", compact ? "" : "sm:flex-row sm:items-center")}>
      <div className={cn("shrink-0", compact ? "" : "sm:w-40")}>
        <p className="text-subtle text-xs">Overall OEE</p>
        <p className="text-foreground mt-1 text-3xl leading-none font-semibold tracking-tight">
          {formatPercentage(oee)}
        </p>
        <div className="mt-2">
          <StatusBadge tone={tone} size="sm">
            {toneLabel}
          </StatusBadge>
        </div>
      </div>

      <div className="min-w-0 flex-1 space-y-3">
        {factors.map((factor) => (
          <MetricBar
            key={factor.key}
            label={factor.label}
            percentage={factor.value}
            tone={factor.key === weakest.key ? "warn" : "info"}
          />
        ))}
        <p className="text-subtle text-[11px]">
          <Icon name="mdi:information-outline" size={12} className="mr-1 inline align-[-1px]" />
          {weakest.label} is the lowest factor at {formatPercentage(weakest.value)}. OEE is
          availability × performance × quality, calculated by the backend.
        </p>
        {cycleTimeWarning && (
          <p className="text-warn-fg text-[11px]">
            <Icon name="mdi:alert-outline" size={12} className="mr-1 inline align-[-1px]" />
            Uncapped performance is {formatPercentage(performanceUncapped)}, which means a recorded
            ideal cycle time is shorter than achievable. Check the component reference data.
          </p>
        )}
      </div>
    </div>
  );
}

/**
 * Planned, produced and target side by side (spec section 6).
 *
 * A stack of three proportional bars against a common scale, so the
 * relationship is immediately readable without duplicating the production trend
 * chart that sits beside it.
 *
 * `achievement` and `efficiency` are the backend's figures, rendered as text.
 * The bar widths are scaled to the largest of the three quantities, which is a
 * drawing decision -- it produces no number anybody reads.
 */
export function TargetVsActual({
  planned,
  produced,
  target,
  achievementPercentage,
  efficiencyPercentage,
  unit = "units",
}: {
  planned: number;
  produced: number;
  target: number;
  achievementPercentage: number;
  efficiencyPercentage: number;
  unit?: string;
}) {
  const scale = Math.max(planned, produced, target, 1);
  const rows = [
    { label: "Produced", value: produced, tone: "info" as Tone, emphasis: true },
    { label: "Target", value: target, tone: "neutral" as Tone, emphasis: false },
    { label: "Planned", value: planned, tone: "neutral" as Tone, emphasis: false },
  ];

  // The backend suppresses the target when a machine or shift filter is
  // applied, because targets have no such dimension. Saying so is better than
  // showing a 0% achievement that means "not applicable".
  const targetSuppressed = target === 0;

  return (
    <div className="space-y-4">
      <div className="space-y-2.5">
        {rows.map((row) => (
          <div key={row.label}>
            <div className="flex items-baseline justify-between gap-2">
              <span
                className={cn(
                  "text-xs",
                  row.emphasis ? "text-foreground font-medium" : "text-muted",
                )}
              >
                {row.label}
              </span>
              <span
                className={cn(
                  "tabular-nums",
                  row.emphasis
                    ? "text-foreground text-sm font-semibold"
                    : "text-muted text-xs font-medium",
                )}
              >
                {formatNumber(row.value)}
                <span className="text-subtle ml-1 font-normal">{unit}</span>
              </span>
            </div>
            <div className="bg-surface-sunken mt-1 h-2 w-full overflow-hidden rounded">
              <div
                className={cn("h-full rounded", TONE_BAR[row.tone])}
                style={{ width: `${(row.value / scale) * 100}%` }}
              />
            </div>
          </div>
        ))}
      </div>

      <dl className="border-border-base grid grid-cols-2 gap-3 border-t pt-3">
        <div>
          <dt className="text-subtle text-xs">Achievement vs target</dt>
          <dd className="text-foreground mt-0.5 text-base font-semibold">
            {targetSuppressed ? "Not applicable" : formatPercentage(achievementPercentage)}
          </dd>
          {targetSuppressed && (
            <p className="text-subtle mt-0.5 text-[11px]">
              Targets are set per line and date, not per machine or shift.
            </p>
          )}
        </div>
        <div>
          <dt className="text-subtle text-xs">Efficiency vs plan</dt>
          <dd className="text-foreground mt-0.5 text-base font-semibold">
            {formatPercentage(efficiencyPercentage)}
          </dd>
        </div>
      </dl>
    </div>
  );
}

/**
 * A segmented bar for a status breakdown (spec sections 8 and 9).
 *
 * The bar is a glance; the legend below carries the count and the label for
 * every segment, so nothing depends on distinguishing two adjacent colours.
 */
export function StatusDistribution({
  segments,
  total,
  itemNoun = "items",
}: {
  segments: { label: string; count: number; tone: Tone }[];
  total: number;
  itemNoun?: string;
}) {
  const present = segments.filter((segment) => segment.count > 0);

  return (
    <div>
      <div
        className="bg-surface-sunken flex h-2.5 w-full overflow-hidden rounded"
        role="img"
        aria-label={
          total === 0
            ? `No ${itemNoun}`
            : `${total} ${itemNoun}: ` +
              present.map((segment) => `${segment.count} ${segment.label}`).join(", ")
        }
      >
        {present.map((segment) => (
          <div
            key={segment.label}
            className={TONE_BAR[segment.tone]}
            style={{ width: `${(segment.count / Math.max(total, 1)) * 100}%` }}
          />
        ))}
      </div>

      <ul className="mt-3 grid grid-cols-2 gap-x-4 gap-y-2 sm:grid-cols-4">
        {segments.map((segment) => (
          <li key={segment.label} className="min-w-0">
            <div className="flex items-center gap-1.5">
              <span
                aria-hidden="true"
                className={cn("size-2 shrink-0 rounded-full", TONE_BAR[segment.tone])}
              />
              <span className="text-subtle truncate text-xs">{segment.label}</span>
            </div>
            <p className="text-foreground mt-0.5 text-lg leading-tight font-semibold">
              {formatNumber(segment.count)}
            </p>
          </li>
        ))}
      </ul>
    </div>
  );
}
