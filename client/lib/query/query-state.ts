/**
 * Reusable query-state derivation (spec sections 16, 18 and 19).
 *
 * TanStack Query exposes `isPending`, `isError`, `data`, `isFetching` and
 * several more, and every component that renders a query has to decide what
 * combination means "show a skeleton" versus "show an empty state". Left to
 * each component, those decisions drift, and the ones that matter get missed --
 * particularly the difference between *loading* and *refetching*, which is what
 * causes a table to blank out every time a filter changes.
 *
 * This module makes that one decision, once. Components read a single
 * discriminated status.
 *
 * THE STATES
 *
 *     loading      first fetch, nothing to show yet          -> skeleton
 *     refreshing   has data, fetching an update              -> subtle indicator
 *     success      has data, idle                            -> content
 *     empty        request succeeded, result has no rows     -> empty state
 *     error        request failed                            -> message + retry
 *
 * `empty` is separated from `success` because they call for different UI and
 * are constantly confused: an empty production list is not an error and not a
 * loading state, and rendering an empty table with headers and no explanation
 * looks broken.
 *
 * `refreshing` is separated from `loading` for the reason spec section 20
 * gives: a refetch must not replace the screen. A component that treats both as
 * "loading" throws away data it already has and flashes.
 */
import type { UseQueryResult } from "@tanstack/react-query";

import { type ApiError, isApiError } from "@/lib/api/errors";

/** The five states a data-driven view can be in. */
export type QueryStatus = "loading" | "refreshing" | "success" | "empty" | "error";

/** Derived view state for one query. */
export interface QueryState<TData> {
  status: QueryStatus;
  /** Present in `success`, `empty` and `refreshing`. */
  data: TData | undefined;
  /** Present only in `error`. Always normalised (spec section 16). */
  error: ApiError | undefined;

  /** First load. Nothing to render yet. */
  isLoading: boolean;
  /** Has data and is fetching an update. Keep the content on screen. */
  isRefreshing: boolean;
  isSuccess: boolean;
  isEmpty: boolean;
  isError: boolean;

  /** Re-run the query. Wired to a retry button. */
  refetch: () => void;
}

/**
 * How a query decides its result is empty.
 *
 * Defaults handle the two shapes the API returns: a bare array, and a paginated
 * envelope. Anything else is never empty unless the caller says how -- guessing
 * (`Object.keys(data).length === 0`, say) would call a summary of all-zero KPIs
 * "empty" when it is a perfectly valid answer.
 */
function defaultIsEmpty(data: unknown): boolean {
  if (Array.isArray(data)) {
    return data.length === 0;
  }
  if (data && typeof data === "object" && "data" in data) {
    const inner = (data as { data: unknown }).data;
    if (Array.isArray(inner)) {
      return inner.length === 0;
    }
  }
  return false;
}

/**
 * Derive view state from a TanStack Query result.
 *
 * @param query The query result.
 * @param isEmpty Overrides the default emptiness test. Supply one when
 *   "no data" means something specific, such as `has_data === false` on a
 *   backend summary.
 */
export function toQueryState<TData>(
  query: UseQueryResult<TData, unknown>,
  isEmpty: (data: TData) => boolean = defaultIsEmpty,
): QueryState<TData> {
  const refetch = () => {
    void query.refetch();
  };

  if (query.isError) {
    return {
      status: "error",
      data: query.data,
      // Every error reaching a component has already been normalised by the
      // Axios interceptor. The guard covers a non-Axios throw, which would
      // otherwise reach a component as an unknown shape.
      error: isApiError(query.error) ? query.error : undefined,
      isLoading: false,
      isRefreshing: false,
      isSuccess: false,
      isEmpty: false,
      isError: true,
      refetch,
    };
  }

  if (query.isPending || query.data === undefined) {
    return {
      status: "loading",
      data: undefined,
      error: undefined,
      isLoading: true,
      isRefreshing: false,
      isSuccess: false,
      isEmpty: false,
      isError: false,
      refetch,
    };
  }

  const empty = isEmpty(query.data);
  // Data in hand and a request in flight. The content stays; the indicator is
  // the caller's to render subtly.
  const refreshing = query.isFetching;

  return {
    status: refreshing ? "refreshing" : empty ? "empty" : "success",
    data: query.data,
    error: undefined,
    isLoading: false,
    isRefreshing: refreshing,
    isSuccess: !empty,
    isEmpty: empty,
    isError: false,
    refetch,
  };
}

/**
 * A message safe to show a user, and whether retrying is worth offering.
 *
 * Spec section 16 asks that components distinguish status codes without each
 * parsing an Axios error. They read this instead.
 */
export interface ErrorPresentation {
  title: string;
  message: string;
  /** Whether a retry button should appear. */
  canRetry: boolean;
  /** Seconds to wait, from `Retry-After` on a 429. */
  retryAfterSeconds?: number;
}

/**
 * Turn an `ApiError` into something renderable.
 *
 * The messages are deliberately plain. The backend already returns a
 * client-safe message, so it is preferred where present; these are the fallback
 * for a transport failure that never reached the server.
 */
export function presentError(error: ApiError | undefined): ErrorPresentation {
  if (!error) {
    return {
      title: "Something went wrong",
      message: "The information could not be loaded.",
      canRetry: true,
    };
  }

  switch (error.kind) {
    case "network":
      return {
        title: "Cannot reach the server",
        message:
          "The dashboard could not contact the service. Check your connection and try again.",
        canRetry: true,
      };
    case "timeout":
      return {
        title: "The request timed out",
        message: "The service took too long to respond. Try again.",
        canRetry: true,
      };
    case "unauthorized":
      // No retry: the session has ended, and retrying would loop. The
      // session-expiry watcher is already redirecting to sign in.
      return {
        title: "Your session has ended",
        message: "Sign in again to continue.",
        canRetry: false,
      };
    case "forbidden":
      // No retry: signing in again changes nothing (spec section 17).
      return {
        title: "You do not have access",
        message:
          "Your role does not permit viewing this information. Contact an administrator if you need it.",
        canRetry: false,
      };
    case "not_found":
      return {
        title: "Not found",
        message: "The requested information does not exist.",
        canRetry: false,
      };
    case "validation":
      return {
        title: "Those filters are not valid",
        message: error.message,
        canRetry: false,
      };
    case "rate_limited":
      // Spec section 18: never hammer. The wait comes from Retry-After.
      return {
        title: "Too many requests",
        message: error.retryAfterSeconds
          ? `Please wait ${error.retryAfterSeconds} seconds and try again.`
          : "Too many requests. Please try again shortly.",
        canRetry: false,
        retryAfterSeconds: error.retryAfterSeconds,
      };
    case "server":
      return {
        title: "The service is unavailable",
        message: "The server had a problem. Try again in a moment.",
        canRetry: true,
      };
    case "canceled":
      return { title: "Cancelled", message: "The request was cancelled.", canRetry: true };
    default:
      return {
        title: "Something went wrong",
        message: error.message,
        canRetry: true,
      };
  }
}

/**
 * Whether an error means the backend is down, as opposed to refusing this
 * request (spec section 29).
 *
 * The distinction drives the UI: an outage shows one application-level banner,
 * where a 403 shows an inline message on the one panel affected.
 */
export function isBackendUnavailable(error: ApiError | undefined): boolean {
  if (!error) {
    return false;
  }
  return error.kind === "network" || error.kind === "timeout" || error.kind === "server";
}
