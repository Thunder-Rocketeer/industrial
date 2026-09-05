/**
 * Central query key registry.
 *
 * Spec section 16: "Query keys must be structured and consistent."
 *
 * Every key is built here so that invalidation after a mutation can target a
 * whole subtree by prefix. For example, invalidating `queryKeys.production.all`
 * clears every production list and summary regardless of the filters they were
 * fetched with, because TanStack Query matches keys by prefix.
 *
 * Convention: `[domain]` -> `[domain, resource]` -> `[domain, resource, params]`.
 * Filter objects are always the last element, so a prefix match stays possible.
 */

/** Filter bags are serialized into the key as-is; keep them plain and stable. */
export type QueryFilters = Record<string, unknown>;

export const queryKeys = {
  dashboard: {
    all: ["dashboard"] as const,
    summary: (date?: string) => ["dashboard", "summary", { date }] as const,
    trends: (filters: QueryFilters = {}) => ["dashboard", "trends", filters] as const,
    alerts: () => ["dashboard", "alerts"] as const,
  },

  production: {
    all: ["production"] as const,
    list: (filters: QueryFilters = {}) => ["production", "list", filters] as const,
    summary: (filters: QueryFilters = {}) => ["production", "summary", filters] as const,
    trend: (filters: QueryFilters = {}) => ["production", "trend", filters] as const,
  },

  quality: {
    all: ["quality"] as const,
    list: (filters: QueryFilters = {}) => ["quality", "list", filters] as const,
    summary: (filters: QueryFilters = {}) => ["quality", "summary", filters] as const,
    defectPareto: (filters: QueryFilters = {}) => ["quality", "defect-pareto", filters] as const,
  },

  inventory: {
    all: ["inventory"] as const,
    list: (filters: QueryFilters = {}) => ["inventory", "list", filters] as const,
    alerts: () => ["inventory", "alerts"] as const,
  },

  machines: {
    all: ["machines"] as const,
    list: (filters: QueryFilters = {}) => ["machines", "list", filters] as const,
    detail: (machineId: string) => ["machines", "detail", machineId] as const,
    summary: () => ["machines", "summary"] as const,
  },

  analytics: {
    all: ["analytics"] as const,
    oee: (filters: QueryFilters = {}) => ["analytics", "oee", filters] as const,
    productionEfficiency: (filters: QueryFilters = {}) =>
      ["analytics", "production-efficiency", filters] as const,
    defects: (filters: QueryFilters = {}) => ["analytics", "defects", filters] as const,
  },

  /** Slow-moving lookup data shared across modules. */
  reference: {
    all: ["reference"] as const,
    components: () => ["reference", "components"] as const,
    lines: () => ["reference", "lines"] as const,
    shifts: () => ["reference", "shifts"] as const,
    defectTypes: () => ["reference", "defect-types"] as const,
  },

  auth: {
    all: ["auth"] as const,
    currentUser: () => ["auth", "current-user"] as const,
  },
} as const;

export type QueryKeys = typeof queryKeys;
