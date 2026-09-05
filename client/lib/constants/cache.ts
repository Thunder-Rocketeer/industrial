/**
 * Client-side cache tiers.
 *
 * Spec section 16 gives starting stale times by data volatility, and section 33
 * sets the dashboard refresh interval. Centralizing them here keeps the values
 * tunable in one place instead of scattering magic numbers through hooks
 * (spec section 47: no magic numbers for important behaviour).
 *
 * These are the *frontend* tiers. Redis TTLs on the backend are configured
 * separately; the two layers are tuned independently.
 */

const SECOND = 1000;
const MINUTE = 60 * SECOND;

/** How long fetched data is considered fresh before a refetch is allowed. */
export const STALE_TIME = {
  /** Dashboard summary and KPI cards. */
  realtime: 30 * SECOND,
  /** Trend and chart data over recent periods. */
  trend: 2 * MINUTE,
  /** Historical analytics that change slowly. */
  historical: 5 * MINUTE,
  /** Reference data: components, machines, lines, shifts, defect types. */
  reference: 30 * MINUTE,
} as const;

/** How long an inactive query stays in the cache before garbage collection. */
export const GC_TIME = {
  default: 10 * MINUTE,
  reference: 60 * MINUTE,
} as const;

/**
 * Polling interval for the executive dashboard (spec section 33).
 * Only the summary endpoints poll; historical analytics never do.
 */
export const DASHBOARD_REFETCH_INTERVAL = 30 * SECOND;

/** Bounds enforced by the backend on list endpoints (spec section 64). */
export const PAGINATION = {
  defaultPageSize: 25,
  maxPageSize: 100,
} as const;
