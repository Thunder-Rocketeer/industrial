"use client";

/**
 * Alert access from the header (spec section 1).
 *
 * A link, not a button with a popover: the alerts page already lists, filters
 * and paginates them properly, and a second miniature implementation in a
 * dropdown would be one more place for the count and the list to disagree.
 *
 * The count comes from `useAlertSummary`, which is cached separately from the
 * alert list precisely so a badge showing one number does not have to fetch and
 * hold every alert (Phase 5, spec section 13).
 *
 * Accessibility: the badge is a colour and a number, so the accessible name
 * spells out the state in words -- "Alerts: 3 open, 1 critical" -- rather than
 * leaving a screen-reader user with "Alerts, 3".
 */
import Link from "next/link";

import { Icon } from "@/components/ui/Icon";
import { useAlertSummary } from "@/hooks/queries/useAlerts";

export function AlertBell() {
  const summary = useAlertSummary();

  const open = summary.data?.total_open ?? 0;
  const critical = summary.data?.critical_count ?? 0;
  const hasAny = open > 0;

  const description = !summary.data
    ? "Alerts"
    : open === 0
      ? "Alerts: none open"
      : `Alerts: ${open} open, ${critical} critical`;

  return (
    <Link
      href="/alerts"
      className="hover:bg-surface-sunken relative flex size-9 items-center justify-center rounded transition-colors"
    >
      <Icon
        name={hasAny ? "mdi:bell-alert-outline" : "mdi:bell-outline"}
        size={18}
        className={critical > 0 ? "text-critical" : "text-muted"}
      />
      {hasAny && (
        <span
          aria-hidden="true"
          className={`absolute top-1 right-1 flex min-w-4 items-center justify-center rounded-full px-1 text-[10px] leading-4 font-semibold text-white ${
            critical > 0 ? "bg-critical" : "bg-warn"
          }`}
        >
          {open > 99 ? "99+" : open}
        </span>
      )}
      <span className="sr-only">{description}</span>
    </Link>
  );
}
