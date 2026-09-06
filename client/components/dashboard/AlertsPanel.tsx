"use client";

/**
 * Alerts (spec section 10).
 *
 * Alerts sit at the top of the dashboard's visual hierarchy because they are
 * the only thing on the screen that asks the reader to *do* something. The
 * backend returns them already ordered by severity then recency, and that order
 * is preserved.
 *
 * Every alert renders its severity as a word. The colour and icon reinforce it
 * and are never the whole message (spec section 10, WCAG 1.4.1).
 *
 * `description` and `title` come from the database as plain strings and are
 * rendered as text by React's default escaping. There is no
 * `dangerouslySetInnerHTML` anywhere in this file, which is what makes a stored
 * `<script>` in an alert description inert (spec section 36).
 */
import Link from "next/link";

import { Icon } from "@/components/ui/Icon";
import { StatusBadge, alertSeverityTone } from "@/components/ui/Status";
import { formatDateTime, formatMinutes } from "@/lib/utils/format";
import type { Alert } from "@/types/alerts";

/** The subject an alert is about, whichever kind it is. */
function alertSubject(alert: Alert): { label: string; href?: string } | null {
  if (alert.machine_name) {
    return {
      label: alert.machine_code
        ? `${alert.machine_code} · ${alert.machine_name}`
        : alert.machine_name,
      href: alert.machine_id ? `/machines/${alert.machine_id}` : undefined,
    };
  }
  if (alert.inventory_item_name) {
    return { label: alert.inventory_item_name, href: "/inventory" };
  }
  if (alert.component_name) {
    return { label: alert.component_name };
  }
  if (alert.line_name) {
    return { label: alert.line_name };
  }
  return null;
}

export function AlertRow({ alert }: { alert: Alert }) {
  const tone = alertSeverityTone(alert.severity);
  const subject = alertSubject(alert);

  return (
    <li className="border-border-base/70 flex gap-3 border-b py-3 first:pt-0 last:border-b-0 last:pb-0">
      <div className="pt-0.5">
        <Icon
          name={
            alert.severity === "CRITICAL"
              ? "mdi:alert-octagon"
              : alert.severity === "WARNING"
                ? "mdi:alert"
                : "mdi:information"
          }
          size={16}
          className={
            tone === "critical" ? "text-critical" : tone === "warn" ? "text-warn" : "text-accent"
          }
        />
      </div>

      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
          <StatusBadge tone={tone} size="sm">
            {alert.severity_label}
          </StatusBadge>
          <span className="text-foreground text-sm font-medium">{alert.title}</span>
        </div>

        <p className="text-muted mt-1 text-xs leading-relaxed">{alert.description}</p>

        <div className="text-subtle mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px]">
          <time dateTime={alert.triggered_at} title={formatDateTime(alert.triggered_at)}>
            {formatMinutes(alert.age_minutes)} ago
          </time>
          {subject && (
            <>
              <span aria-hidden="true">·</span>
              {subject.href ? (
                <Link
                  href={subject.href}
                  className="hover:text-foreground underline-offset-2 hover:underline"
                >
                  {subject.label}
                </Link>
              ) : (
                <span>{subject.label}</span>
              )}
            </>
          )}
          <span aria-hidden="true">·</span>
          <span>{alert.alert_type_label}</span>
        </div>
      </div>
    </li>
  );
}

export function AlertList({ alerts }: { alerts: Alert[] }) {
  return (
    <ul className="flex flex-col">
      {alerts.map((alert) => (
        <AlertRow key={alert.id} alert={alert} />
      ))}
    </ul>
  );
}
