"use client";

/**
 * The application-level "service unavailable" notice (spec section 29).
 *
 * Structure and behaviour only. Phase 5 builds the data layer, not the visual
 * design (spec section 34), so this carries semantic markup and no styling
 * beyond what it needs to be readable and announced correctly. Phase 6 styles
 * it without changing what it says or when it appears.
 *
 * Three requirements from section 29, in order:
 *
 *   - it states that the service is unreachable, once, rather than letting
 *     eight panels each report the same outage;
 *   - it offers a retry that refetches the failing queries;
 *   - it does not hide the data already on screen. Last-known values stay
 *     visible with the time they were fetched, so nobody mistakes them for
 *     current.
 */
import { useBackendStatus } from "@/hooks/useBackendStatus";
import { formatDateTime } from "@/lib/utils/format";

export interface BackendUnavailableProps {
  /** Rendered beneath the notice: the last-known data (spec section 29). */
  children?: React.ReactNode;
}

export function BackendUnavailable({ children }: BackendUnavailableProps) {
  const { isUnavailable, lastSuccessAt, retry } = useBackendStatus();

  /*
   * `children` MUST stay at a fixed position in this output. Do not restore the
   * early `return <>{children}</>` that used to sit here.
   *
   * That version returned a one-child fragment while healthy and a two-child
   * fragment while unavailable, which moved `children` from index 0 to index 1.
   * React reconciles unkeyed siblings by position, so the whole page below this
   * point was torn down and rebuilt every time the banner appeared -- and that
   * turned a single failed request into a permanent retry storm:
   *
   *   1. `/dashboard/summary` fails its two retries and settles into `error`.
   *   2. `isUnavailable` flips true, so this component re-renders and the page
   *      subtree remounts.
   *   3. A remounted observer on a failed query refetches -- `retryOnMount` is
   *      on by default -- with `failureCount` back at zero, so the two-retry
   *      cap in `shouldRetry` never actually ends anything.
   *   4. The query is pending again, `isUnavailable` flips back to false, the
   *      subtree remounts a second time, and the cycle restarts.
   *
   * Measured against the running application with `/dashboard/summary`
   * returning 500: a clean 1s / 2s / ~80ms cycle repeating indefinitely -- one
   * request per second, forever, at a server that has just told us it is
   * failing. Meanwhile the dashboard sat on skeletons and showed neither the
   * per-panel error nor this banner, because neither state ever lasted longer
   * than the ~80ms before the next remount.
   *
   * Rendering the banner as a conditional expression in a fixed slot keeps
   * `children` at index 1 in every render, so it is never remounted.
   */
  return (
    <>
      {/*
        `role="alert"` with `aria-live="assertive"`: an outage is the one
        condition worth interrupting a screen-reader user for, because every
        number on the page has stopped updating (spec section 45).
      */}
      {isUnavailable && (
        <div role="alert" aria-live="assertive">
          <h2>The service is unavailable</h2>
          <p>
            The dashboard cannot reach the server. Figures shown below are the last values received
            and are not updating.
          </p>
          {lastSuccessAt !== null && (
            <p>
              Last updated{" "}
              <time dateTime={new Date(lastSuccessAt).toISOString()}>
                {formatDateTime(new Date(lastSuccessAt).toISOString())}
              </time>
            </p>
          )}
          <button type="button" onClick={retry}>
            Retry
          </button>
        </div>
      )}
      {children}
    </>
  );
}
