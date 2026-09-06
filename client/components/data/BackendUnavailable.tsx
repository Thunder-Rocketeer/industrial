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

  if (!isUnavailable) {
    return <>{children}</>;
  }

  return (
    <>
      {/*
        `role="alert"` with `aria-live="assertive"`: an outage is the one
        condition worth interrupting a screen-reader user for, because every
        number on the page has stopped updating (spec section 45).
      */}
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
      {children}
    </>
  );
}
