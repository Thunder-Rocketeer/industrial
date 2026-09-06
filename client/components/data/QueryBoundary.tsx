"use client";

/**
 * Renders the five Phase 5 query states (spec sections 13, 14, 15 and 16).
 *
 * Every data-driven region on the dashboard goes through this, so the loading /
 * empty / error decision is made once instead of drifting across forty
 * components.
 *
 * The subtle part is `refreshing`. Spec section 16 requires that a background
 * refetch must not flash or reset the dashboard, and Phase 5 already separates
 * `refreshing` from `loading` for that reason. Here that separation becomes
 * concrete: in `refreshing` the previous content stays mounted -- same DOM,
 * same scroll position, same focus -- and the only change is a small indicator
 * in the section header. Treating it as loading would swap the content for a
 * skeleton every thirty seconds, which is the exact behaviour the spec forbids.
 */
import type { ReactNode } from "react";

import { EmptyState, ErrorState, LoadingRegion } from "@/components/ui/States";
import type { QueryState } from "@/lib/query/query-state";

export interface QueryBoundaryProps<TData> {
  query: QueryState<TData>;
  /** Skeleton for the first load. Shape it like the content it replaces. */
  skeleton: ReactNode;
  /** Announced while loading, e.g. "Loading production trend". */
  loadingLabel: string;
  /** Rendered with data in `success`, `empty` and `refreshing`. */
  children: (data: TData) => ReactNode;

  emptyTitle?: string;
  emptyMessage?: string;
  emptyIcon?: string;
  /** Render children even when the result is empty, e.g. a table that keeps
   *  its own headers and shows the empty message in its body. */
  renderEmptyAsContent?: boolean;

  /** Overrides the error title, e.g. "Unable to refresh production data." */
  errorTitle?: string;
  compact?: boolean;
}

export function QueryBoundary<TData>({
  query,
  skeleton,
  loadingLabel,
  children,
  emptyTitle = "No data",
  emptyMessage,
  emptyIcon,
  renderEmptyAsContent = false,
  errorTitle,
  compact = false,
}: QueryBoundaryProps<TData>) {
  if (query.isLoading) {
    return <LoadingRegion label={loadingLabel}>{skeleton}</LoadingRegion>;
  }

  if (query.isError) {
    return (
      <ErrorState
        error={query.error}
        title={errorTitle}
        onRetry={query.refetch}
        compact={compact}
      />
    );
  }

  if (query.isEmpty && !renderEmptyAsContent) {
    return (
      <EmptyState title={emptyTitle} message={emptyMessage} icon={emptyIcon} compact={compact} />
    );
  }

  if (query.data === undefined) {
    // Not reachable through the states above; a defensive branch so a future
    // change cannot make this component render `undefined` into a child.
    return <EmptyState title={emptyTitle} message={emptyMessage} compact={compact} />;
  }

  return <>{children(query.data)}</>;
}

/**
 * A small "updating" marker for a section header.
 *
 * Deliberately not a spinner over the content: during a refresh the numbers on
 * screen are still the most recent ones the server sent, and hiding them behind
 * an overlay makes the dashboard less useful for the second it takes to load.
 */
export function RefreshingIndicator({ active }: { active: boolean }) {
  if (!active) {
    return null;
  }
  return (
    <span
      className="text-subtle inline-flex items-center gap-1 text-[11px]"
      role="status"
      aria-live="polite"
    >
      <span className="bg-accent size-1.5 animate-pulse rounded-full" aria-hidden="true" />
      Updating
    </span>
  );
}
