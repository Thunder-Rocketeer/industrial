/**
 * Loading, empty and error states (spec sections 13, 14 and 15).
 *
 * Every data-driven region on the dashboard renders one of these rather than
 * inventing its own. Three decisions are baked in:
 *
 *   1. **Skeletons are per-section, and shaped like the content.** A single
 *      page-wide spinner tells the user nothing about what is arriving, and a
 *      skeleton with the wrong shape produces a layout jump the moment data
 *      lands -- which is the thing skeletons exist to prevent (CLS).
 *
 *   2. **A retry button appears only when retrying could work.** `canRetry`
 *      comes from Phase 5's `presentError`, which returns false for 401, 403,
 *      404, 422 and 429. Offering "Try again" on a 403 invites the user to
 *      click a button that will fail identically, forever.
 *
 *   3. **No technical detail reaches the screen.** The message shown is the
 *      backend's user-safe `message` or a plain fallback -- never a status
 *      line, a stack, or a URL.
 */
import type { ReactNode } from "react";

import { Button } from "@/components/ui/Button";
import { Icon } from "@/components/ui/Icon";
import type { ApiError } from "@/lib/api/errors";
import { presentError } from "@/lib/query/query-state";
import { cn } from "@/lib/utils/cn";

// =============================================================================
// Skeletons
// =============================================================================

/**
 * A shimmering block.
 *
 * The pulse is suppressed under `prefers-reduced-motion` by the global rule in
 * `globals.css`, where it degrades to a static grey block that still
 * communicates "content is coming".
 */
export function Skeleton({ className }: { className?: string }) {
  return <div className={cn("bg-surface-sunken animate-pulse rounded", className)} />;
}

/**
 * A skeleton region, announced to assistive technology.
 *
 * `role="status"` with `aria-live="polite"` and a visually hidden sentence: a
 * screen-reader user is told the section is loading instead of meeting silence
 * and an empty region.
 */
export function LoadingRegion({
  label,
  children,
  className,
}: {
  label: string;
  children: ReactNode;
  className?: string;
}) {
  return (
    <div role="status" aria-busy="true" aria-live="polite" className={cn(className)}>
      {children}
      <span className="sr-only">{label}</span>
    </div>
  );
}

/** Placeholder shaped like a KPI card. */
export function KpiCardSkeleton() {
  return (
    <div className="border-border-base bg-surface rounded-md border p-4">
      <Skeleton className="h-3 w-24" />
      <Skeleton className="mt-3 h-7 w-28" />
      <Skeleton className="mt-3 h-3 w-32" />
    </div>
  );
}

/** Placeholder shaped like a chart: axis strip plus plot area. */
export function ChartSkeleton({ height = 260 }: { height?: number }) {
  return (
    <div className="flex flex-col gap-2" style={{ height }}>
      <Skeleton className="min-h-0 flex-1" />
      <div className="flex justify-between gap-2">
        <Skeleton className="h-2.5 w-10" />
        <Skeleton className="h-2.5 w-10" />
        <Skeleton className="h-2.5 w-10" />
        <Skeleton className="h-2.5 w-10" />
      </div>
    </div>
  );
}

/** Placeholder shaped like a table, with a header row and body rows. */
export function TableSkeleton({ rows = 6, columns = 5 }: { rows?: number; columns?: number }) {
  return (
    <div className="w-full">
      <div className="border-border-base flex gap-4 border-b px-4 py-2.5">
        {Array.from({ length: columns }).map((_, index) => (
          <Skeleton key={index} className="h-3 flex-1" />
        ))}
      </div>
      {Array.from({ length: rows }).map((_, rowIndex) => (
        <div key={rowIndex} className="border-border-base/60 flex gap-4 border-b px-4 py-3">
          {Array.from({ length: columns }).map((_, columnIndex) => (
            <Skeleton key={columnIndex} className="h-3.5 flex-1" />
          ))}
        </div>
      ))}
    </div>
  );
}

/** Placeholder shaped like a list of alerts or records. */
export function ListSkeleton({ rows = 4 }: { rows?: number }) {
  return (
    <ul className="space-y-3">
      {Array.from({ length: rows }).map((_, index) => (
        <li key={index} className="flex gap-3">
          <Skeleton className="size-4 shrink-0 rounded-full" />
          <div className="min-w-0 flex-1 space-y-2">
            <Skeleton className="h-3.5 w-2/5" />
            <Skeleton className="h-3 w-4/5" />
          </div>
        </li>
      ))}
    </ul>
  );
}

// =============================================================================
// Empty
// =============================================================================

/**
 * A successful request that returned nothing.
 *
 * Distinct from an error on purpose: "no production records in this range" is a
 * fact about the factory, not a fault, and the wording says which range so the
 * user knows what to change (spec section 15).
 */
export function EmptyState({
  title,
  message,
  icon = "mdi:database-search-outline",
  action,
  compact = false,
}: {
  title: string;
  message?: string;
  icon?: string;
  action?: ReactNode;
  compact?: boolean;
}) {
  return (
    <div
      className={cn(
        "flex flex-col items-center justify-center text-center",
        compact ? "px-4 py-6" : "px-6 py-10",
      )}
    >
      <Icon name={icon} size={compact ? 22 : 28} className="text-subtle" />
      <p className="text-foreground mt-3 text-sm font-medium">{title}</p>
      {message && <p className="text-subtle mt-1 max-w-sm text-xs">{message}</p>}
      {action && <div className="mt-4">{action}</div>}
    </div>
  );
}

// =============================================================================
// Error
// =============================================================================

/**
 * A failed request.
 *
 * `role="alert"` so the failure is announced rather than sitting silently in a
 * panel a screen-reader user has already passed.
 */
export function ErrorState({
  error,
  /** Overrides the generic title, e.g. "Unable to refresh production data." */
  title,
  onRetry,
  compact = false,
}: {
  error: ApiError | undefined;
  title?: string;
  onRetry?: () => void;
  compact?: boolean;
}) {
  const presentation = presentError(error);

  return (
    <div
      role="alert"
      className={cn(
        "flex flex-col items-center justify-center text-center",
        compact ? "px-4 py-6" : "px-6 py-10",
      )}
    >
      <Icon name="mdi:alert-circle-outline" size={compact ? 22 : 28} className="text-critical" />
      <p className="text-foreground mt-3 text-sm font-medium">{title ?? presentation.title}</p>
      <p className="text-subtle mt-1 max-w-sm text-xs">{presentation.message}</p>
      {presentation.canRetry && onRetry && (
        <Button size="sm" icon="mdi:refresh" onClick={onRetry} className="mt-4">
          Try again
        </Button>
      )}
    </div>
  );
}
