/**
 * Central query key registry.
 *
 * Spec section 16: "Query keys must be structured and consistent." Every key in
 * the application is built here. A component that writes its own string key
 * creates a cache entry nothing else can find or invalidate, which is how a
 * mutation ends up leaving a stale table on screen.
 *
 * SHAPE
 *
 *     [domain]                       -> [domain, resource]  -> [domain, resource, params]
 *     ["production"]                    ["production","list"]  ["production","list",{...}]
 *
 * TanStack Query matches keys by prefix, so invalidating `queryKeys.production.all`
 * clears every production list, summary and trend regardless of the filters they
 * were fetched under. That is the point of the hierarchy, and the reason filters
 * are always the *last* element.
 *
 * FILTERS ARE NORMALISED BEFORE THEY REACH A KEY
 *
 * `{page: 1}` and `{page: 1, machine_id: undefined}` describe the same query.
 * Without normalisation they would produce two cache entries, two requests, and
 * a refetch that appears to do nothing. `normalizeFilters` drops absent values
 * and sorts the rest, so an equal filter set always yields an equal key.
 */
import { normalizeFilters } from "@/lib/api/params";

/** Filter bags are normalised into the key; keep them plain and serialisable. */
export type QueryFilters = Record<string, unknown>;

/** Normalise a filter object for use as the final key element. */
function keyFilters(filters: object | undefined): Record<string, unknown> {
  return normalizeFilters(filters);
}

export const queryKeys = {
  dashboard: {
    all: ["dashboard"] as const,
    summary: () => ["dashboard", "summary"] as const,
    trends: (filters: object = {}) => ["dashboard", "trends", keyFilters(filters)] as const,
  },

  production: {
    all: ["production"] as const,
    list: (filters: object = {}) => ["production", "list", keyFilters(filters)] as const,
    summary: (filters: object = {}) => ["production", "summary", keyFilters(filters)] as const,
    trend: (filters: object = {}) => ["production", "trend", keyFilters(filters)] as const,
    byDimension: (dimension: string, filters: object = {}) =>
      ["production", "by-dimension", dimension, keyFilters(filters)] as const,
  },

  quality: {
    all: ["quality"] as const,
    list: (filters: object = {}) => ["quality", "list", keyFilters(filters)] as const,
    summary: (filters: object = {}) => ["quality", "summary", keyFilters(filters)] as const,
    defects: (filters: object = {}) => ["quality", "defects", keyFilters(filters)] as const,
    trend: (filters: object = {}) => ["quality", "trend", keyFilters(filters)] as const,
    byDimension: (dimension: string, filters: object = {}) =>
      ["quality", "by-dimension", dimension, keyFilters(filters)] as const,
  },

  inventory: {
    all: ["inventory"] as const,
    list: (filters: object = {}) => ["inventory", "list", keyFilters(filters)] as const,
    summary: () => ["inventory", "summary"] as const,
    alerts: (limit?: number) => ["inventory", "alerts", { limit }] as const,
    detail: (itemId: string) => ["inventory", "detail", itemId] as const,
    transactions: (itemId: string, filters: object = {}) =>
      ["inventory", "transactions", itemId, keyFilters(filters)] as const,
    trend: (itemId: string, limit?: number) => ["inventory", "trend", itemId, { limit }] as const,
  },

  machines: {
    all: ["machines"] as const,
    list: (filters: object = {}) => ["machines", "list", keyFilters(filters)] as const,
    summary: () => ["machines", "summary"] as const,
    detail: (machineId: string, filters: object = {}) =>
      ["machines", "detail", machineId, keyFilters(filters)] as const,
  },

  analytics: {
    all: ["analytics"] as const,
    oee: (filters: object = {}) => ["analytics", "oee", keyFilters(filters)] as const,
    oeeTrend: (filters: object = {}) => ["analytics", "oee-trend", keyFilters(filters)] as const,
    oeeByMachine: (filters: object = {}) =>
      ["analytics", "oee-by-machine", keyFilters(filters)] as const,
    efficiency: (filters: object = {}) => ["analytics", "efficiency", keyFilters(filters)] as const,
    efficiencyTrend: (filters: object = {}) =>
      ["analytics", "efficiency-trend", keyFilters(filters)] as const,
    downtime: (filters: object = {}) => ["analytics", "downtime", keyFilters(filters)] as const,
    defects: (filters: object = {}) => ["analytics", "defects", keyFilters(filters)] as const,
  },

  alerts: {
    all: ["alerts"] as const,
    list: (filters: object = {}) => ["alerts", "list", keyFilters(filters)] as const,
    active: (limit?: number) => ["alerts", "active", { limit }] as const,
    summary: () => ["alerts", "summary"] as const,
  },

  maintenance: {
    all: ["maintenance"] as const,
    list: (filters: object = {}) => ["maintenance", "list", keyFilters(filters)] as const,
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
    status: () => ["auth", "status"] as const,
  },
} as const;

export type QueryKeys = typeof queryKeys;
