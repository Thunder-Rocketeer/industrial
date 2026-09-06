/**
 * Status vocabulary (spec sections 4, 10 and 32).
 *
 * The rule this file exists to enforce, from spec section 45 and WCAG 1.4.1:
 * **status is never conveyed by colour alone.** A `StatusBadge` always renders
 * a word. The dot and the tint are reinforcement for the ~8% of men with a
 * colour-vision deficiency, for a monochrome print-out, and for a screen washed
 * out by factory-floor daylight -- all of which are ordinary conditions here,
 * not edge cases.
 *
 * Everything maps down to four tones, so a machine status, an alert severity,
 * a stock level and a KPI verdict all read the same way.
 */
import type { ReactNode } from "react";

import { Icon } from "@/components/ui/Icon";
import { cn } from "@/lib/utils/cn";

/** The four tones every status in the application collapses to. */
export type Tone = "good" | "warn" | "critical" | "neutral" | "info";

const TONE_STYLES: Record<Tone, { badge: string; dot: string; icon: string }> = {
  good: {
    badge: "bg-good-soft text-good-fg border-good/25",
    dot: "bg-good",
    icon: "mdi:check-circle",
  },
  warn: {
    badge: "bg-warn-soft text-warn-fg border-warn/25",
    dot: "bg-warn",
    icon: "mdi:alert",
  },
  critical: {
    badge: "bg-critical-soft text-critical-fg border-critical/25",
    dot: "bg-critical",
    icon: "mdi:alert-octagon",
  },
  neutral: {
    badge: "bg-neutral-soft text-neutral-fg border-border-base",
    dot: "bg-neutral-status",
    icon: "mdi:minus-circle-outline",
  },
  info: {
    badge: "bg-accent-soft text-accent border-accent/25",
    dot: "bg-accent",
    icon: "mdi:information",
  },
};

export interface StatusBadgeProps {
  tone: Tone;
  /** The word. Required -- there is no colour-only variant by design. */
  children: ReactNode;
  /** Show the tone icon as well as the dot. */
  withIcon?: boolean;
  size?: "sm" | "md";
  className?: string;
}

export function StatusBadge({
  tone,
  children,
  withIcon = false,
  size = "md",
  className,
}: StatusBadgeProps) {
  const styles = TONE_STYLES[tone];

  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded border font-medium whitespace-nowrap",
        size === "sm" ? "px-1.5 py-0.5 text-[11px]" : "px-2 py-0.5 text-xs",
        styles.badge,
        className,
      )}
    >
      {withIcon ? (
        <Icon name={styles.icon} size={size === "sm" ? 12 : 14} />
      ) : (
        <span className={cn("size-1.5 shrink-0 rounded-full", styles.dot)} aria-hidden="true" />
      )}
      {children}
    </span>
  );
}

/**
 * A bare status dot, for use in a table cell that already shows the word beside
 * it. Hidden from assistive technology, because the word is the label.
 */
export function StatusDot({ tone, className }: { tone: Tone; className?: string }) {
  return (
    <span
      aria-hidden="true"
      className={cn("inline-block size-2 shrink-0 rounded-full", TONE_STYLES[tone].dot, className)}
    />
  );
}

// =============================================================================
// Mapping backend enums to tones
// =============================================================================

/**
 * These functions map a *code* to a colour. They never invent the label -- the
 * backend sends `status_label`, `severity_label` and so on, and that string is
 * what gets rendered (spec sections 8, 9 and 10). Deriving display text here
 * would put a second vocabulary in the UI that drifts from the API's.
 */

export function machineStatusTone(status: string): Tone {
  switch (status) {
    case "RUNNING":
      return "good";
    case "IDLE":
      return "neutral";
    case "MAINTENANCE":
      return "warn";
    case "OFFLINE":
      return "critical";
    default:
      return "neutral";
  }
}

export function inventoryStatusTone(status: string): Tone {
  switch (status) {
    case "HEALTHY":
      return "good";
    case "LOW":
      return "warn";
    case "CRITICAL":
      return "critical";
    // Overstock ties up cash and floor space, but nothing stops if it is
    // ignored today. It is a note, not an alarm.
    case "OVERSTOCKED":
      return "info";
    default:
      return "neutral";
  }
}

export function alertSeverityTone(severity: string): Tone {
  switch (severity) {
    case "CRITICAL":
      return "critical";
    case "WARNING":
      return "warn";
    case "INFO":
      return "info";
    default:
      return "neutral";
  }
}

export function maintenanceStatusTone(status: string): Tone {
  switch (status) {
    case "COMPLETED":
      return "good";
    case "IN_PROGRESS":
      return "info";
    case "SCHEDULED":
      return "neutral";
    case "CANCELLED":
      return "neutral";
    default:
      return "neutral";
  }
}

/** KPI verdicts, which the backend computes and sends as `status`. */
export function kpiStatusTone(status: string): Tone {
  switch (status) {
    case "good":
      return "good";
    case "warning":
      return "warn";
    case "critical":
      return "critical";
    default:
      return "neutral";
  }
}

export function alertStatusTone(status: string): Tone {
  switch (status) {
    case "OPEN":
      return "critical";
    case "ACKNOWLEDGED":
      return "warn";
    case "RESOLVED":
      return "good";
    default:
      return "neutral";
  }
}
