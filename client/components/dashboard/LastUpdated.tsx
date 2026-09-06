"use client";

/**
 * "Updated 24 seconds ago", with a manual refresh (spec sections 3 and 16).
 *
 * Spec section 3 is explicit that the wording must not overstate what is
 * happening: the dashboard polls every 30 seconds, so it does not say "live".
 * The difference matters operationally -- somebody watching a machine go down
 * needs to know whether they are looking at this second or at half a minute
 * ago.
 *
 * The elapsed time is recomputed on a one-second timer rather than on render,
 * because otherwise the label freezes at "0 seconds ago" until the next
 * refetch, which is precisely when it is least true.
 *
 * The exact timestamp goes in `<time dateTime>` and in the tooltip, so the
 * approximate phrasing never becomes the only record of when data arrived.
 */
import { useEffect, useState } from "react";

import { Button } from "@/components/ui/Button";
import { formatDateTime } from "@/lib/utils/format";

function phrase(secondsAgo: number): string {
  if (secondsAgo < 5) {
    return "just now";
  }
  if (secondsAgo < 60) {
    return `${secondsAgo} seconds ago`;
  }
  const minutes = Math.floor(secondsAgo / 60);
  if (minutes < 60) {
    return `${minutes} ${minutes === 1 ? "minute" : "minutes"} ago`;
  }
  const hours = Math.floor(minutes / 60);
  return `${hours} ${hours === 1 ? "hour" : "hours"} ago`;
}

export function LastUpdated({
  /** Epoch milliseconds of the last successful fetch. */
  at,
  isRefreshing,
  onRefresh,
}: {
  at: number | null;
  isRefreshing?: boolean;
  onRefresh?: () => void;
}) {
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    if (at === null) {
      return;
    }
    const timer = window.setInterval(() => setNow(Date.now()), 1_000);
    return () => window.clearInterval(timer);
  }, [at]);

  const secondsAgo = at === null ? null : Math.max(0, Math.floor((now - at) / 1000));
  const iso = at === null ? undefined : new Date(at).toISOString();

  return (
    <div className="text-subtle flex flex-wrap items-center gap-x-3 gap-y-1 text-xs">
      <span className="inline-flex items-center gap-1.5">
        {isRefreshing ? (
          <>
            <span className="bg-accent size-1.5 animate-pulse rounded-full" aria-hidden="true" />
            <span role="status" aria-live="polite">
              Refreshing…
            </span>
          </>
        ) : secondsAgo === null ? (
          <span>Not yet loaded</span>
        ) : (
          <>
            <span className="bg-good size-1.5 rounded-full" aria-hidden="true" />
            <span>
              Updated{" "}
              <time dateTime={iso} title={iso ? formatDateTime(iso) : undefined}>
                {phrase(secondsAgo)}
              </time>
            </span>
          </>
        )}
      </span>

      <span aria-hidden="true" className="text-border-strong hidden sm:inline">
        |
      </span>
      <span>Refreshes every 30 seconds</span>

      {onRefresh && (
        <Button
          size="sm"
          variant="ghost"
          icon="mdi:refresh"
          onClick={onRefresh}
          disabled={isRefreshing}
        >
          Refresh
        </Button>
      )}
    </div>
  );
}
