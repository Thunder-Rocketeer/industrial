/**
 * Transport-level API contract types.
 *
 * These mirror the response envelopes defined in spec section 24 and the error
 * shape from section 68. Domain types (production, quality, inventory, ...)
 * live in their own modules under `types/` and are introduced with the
 * endpoints that return them.
 */

/** Envelope for single-resource and aggregate responses. */
export interface ApiEnvelope<TData> {
  data: TData;
}

/** Pagination metadata returned alongside every list endpoint. */
export interface PaginationMeta {
  page: number;
  page_size: number;
  total: number;
}

/** Envelope for paginated list responses. */
export interface PaginatedResponse<TItem> {
  data: TItem[];
  pagination: PaginationMeta;
}

/**
 * Error body returned by the backend exception handlers.
 *
 * Spec section 68: the backend never leaks stack traces, SQL, or connection
 * details. `code` is a stable machine-readable identifier; `message` is safe to
 * render directly to a user.
 */
export interface ApiErrorBody {
  error: {
    code: string;
    message: string;
    /** Field-level validation detail, present on 422 responses. */
    details?: Record<string, string[]>;
  };
}

/** Standard query parameters accepted by paginated list endpoints. */
export interface PaginationParams {
  page?: number;
  page_size?: number;
}

/** Standard sort parameters. The backend validates fields against an allow-list. */
export interface SortParams {
  sort_by?: string;
  sort_dir?: "asc" | "desc";
}

/** Inclusive date-range filter. Dates are ISO-8601 strings in UTC. */
export interface DateRangeParams {
  start_date?: string;
  end_date?: string;
}
