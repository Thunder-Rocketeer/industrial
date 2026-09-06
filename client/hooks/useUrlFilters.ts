"use client";

/**
 * Filter state, kept in the URL (spec sections 27 and 28).
 *
 * Filters live in the query string rather than in React state, which buys three
 * things spec section 28 asks for and that component state cannot give:
 * reloading keeps the view, Back and Forward step through filter changes, and a
 * filtered view can be pasted into a message.
 *
 * Rules enforced here:
 *
 *  - **Only allow-listed keys are read or written.** An unknown parameter in
 *    the URL is ignored rather than passed through to the API, so a crafted
 *    link cannot inject a query parameter the page never intended to send.
 *  - **Empty means absent.** Clearing a filter removes the key instead of
 *    leaving `?machine_id=`, which the backend rejects as a malformed UUID.
 *  - **Nothing sensitive goes in the URL** (spec section 28). These are ids and
 *    dates that the API authorizes independently on every request; URLs end up
 *    in history, referrers and screenshots, so nothing else belongs here.
 *  - **`push`, so Back undoes a filter.** Reaching a filtered view and pressing
 *    Back should clear the filter, not leave the page. Verified in a real
 *    browser by `e2e/pages.spec.ts`.
 */
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useCallback, useMemo } from "react";

export type FilterValues<TKey extends string> = Partial<Record<TKey, string>>;

export interface UseUrlFiltersResult<TKey extends string> {
  /** Current values, restricted to the allow-listed keys. */
  filters: FilterValues<TKey>;
  /** Set one key. Pass undefined or "" to clear it. */
  setFilter: (key: TKey, value: string | undefined) => void;
  /** Set several keys at once, e.g. both ends of a date range. */
  setFilters: (values: FilterValues<TKey>) => void;
  /** Remove every allow-listed key, leaving anything else untouched. */
  reset: () => void;
  /** Whether any allow-listed filter is set. Drives the "Clear" button. */
  hasActiveFilters: boolean;
  activeCount: number;
}

export function useUrlFilters<TKey extends string>(
  /** The only keys this page reads from or writes to the URL. */
  allowedKeys: readonly TKey[],
): UseUrlFiltersResult<TKey> {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();

  // Depend on the serialized string, not the object: `useSearchParams` returns
  // a new instance each render, which would make every memo below recompute.
  const search = searchParams.toString();

  const filters = useMemo(() => {
    const params = new URLSearchParams(search);
    const result: FilterValues<TKey> = {};
    for (const key of allowedKeys) {
      const value = params.get(key);
      if (value !== null && value.trim() !== "") {
        result[key] = value;
      }
    }
    return result;
    // `allowedKeys` is a module-level constant at every call site.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [search]);

  const commit = useCallback(
    (mutate: (params: URLSearchParams) => void) => {
      const params = new URLSearchParams(search);
      mutate(params);
      const query = params.toString();
      /*
       * `push`, so Back steps through filter changes.
       *
       * Phase 6 used `replace`, reasoning that adjusting a date range should
       * not stack history entries. In a browser that turned out to be the
       * wrong trade: choosing a machine and then pressing Back left the page
       * entirely instead of clearing the filter, which is not what Back means
       * to anyone. Spec section 28 asks for refresh, back/forward and sharing
       * to all work over filter state, and only `push` delivers the middle one.
       *
       * The entry-stacking worry does not apply to what these controls
       * actually are: selects commit once per choice, and date inputs fire on
       * a completed date. The one control that could stack entries -- free
       * text -- debounces before it ever reaches this function.
       */
      router.push(query ? `${pathname}?${query}` : pathname, { scroll: false });
    },
    [router, pathname, search],
  );

  const setFilter = useCallback(
    (key: TKey, value: string | undefined) => {
      if (!allowedKeys.includes(key)) {
        return;
      }
      commit((params) => {
        if (value === undefined || value.trim() === "") {
          params.delete(key);
        } else {
          params.set(key, value.trim());
        }
      });
    },
    [commit, allowedKeys],
  );

  const setFilters = useCallback(
    (values: FilterValues<TKey>) => {
      commit((params) => {
        for (const [key, value] of Object.entries(values) as [TKey, string | undefined][]) {
          if (!allowedKeys.includes(key)) {
            continue;
          }
          if (value === undefined || value.trim() === "") {
            params.delete(key);
          } else {
            params.set(key, value.trim());
          }
        }
      });
    },
    [commit, allowedKeys],
  );

  const reset = useCallback(() => {
    commit((params) => {
      for (const key of allowedKeys) {
        params.delete(key);
      }
    });
  }, [commit, allowedKeys]);

  const activeCount = Object.keys(filters).length;

  return {
    filters,
    setFilter,
    setFilters,
    reset,
    hasActiveFilters: activeCount > 0,
    activeCount,
  };
}

/**
 * A default date range: the last `days` days, ending today, in UTC.
 *
 * UTC throughout, matching the backend, which stores and returns everything in
 * UTC. Building the range from local time would shift the window by a day for
 * anyone west of Greenwich and silently return different rows than the same
 * link opened elsewhere.
 *
 * The result is memo-safe: it is computed from the current date, so callers
 * should compute it once rather than inline in a render.
 */
export function defaultDateRange(days: number): { start_date: string; end_date: string } {
  const end = new Date();
  const start = new Date(end);
  start.setUTCDate(start.getUTCDate() - (days - 1));

  const iso = (date: Date) => date.toISOString().slice(0, 10);
  return { start_date: iso(start), end_date: iso(end) };
}
