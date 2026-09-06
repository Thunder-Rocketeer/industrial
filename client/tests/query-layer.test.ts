/**
 * Query keys, retry policy, and derived view state (spec section 31).
 *
 * These are the rules that decide what is cached together, what is retried, and
 * what a component renders. They are pure, so they are tested directly rather
 * than through a rendered hook.
 */
import { describe, expect, it } from "vitest";

import { ApiError } from "@/lib/api/errors";
import { shouldRetry } from "@/lib/query/query-client";
import { queryKeys } from "@/lib/query/query-keys";
import { isBackendUnavailable, presentError } from "@/lib/query/query-state";
import { clampedPageIndex, toPaginationView, toQueryFilters } from "@/lib/table/server-table";

describe("query keys", () => {
  it("nests domain, resource and parameters", () => {
    const key = queryKeys.production.list({ page: 1 });
    expect(key[0]).toBe("production");
    expect(key[1]).toBe("list");
  });

  it("gives equal filters an equal key regardless of unset properties", () => {
    // Two components asking for the same data must share one cache entry.
    // Without normalization these differ and the request is made twice.
    expect(queryKeys.production.list({ page: 1 })).toEqual(
      queryKeys.production.list({ page: 1, machine_id: undefined }),
    );
  });

  it("gives different filters different keys", () => {
    expect(queryKeys.production.list({ page: 1 })).not.toEqual(
      queryKeys.production.list({ page: 2 }),
    );
  });

  it("keeps a domain prefix that invalidates everything beneath it", () => {
    const domain = queryKeys.production.all;
    const list = queryKeys.production.list({ page: 1 });
    // Prefix matching is how TanStack Query invalidates a whole domain, so the
    // list key must start with the domain key.
    expect(list.slice(0, domain.length)).toEqual([...domain]);
  });

  it("separates domains that would otherwise collide", () => {
    expect(queryKeys.production.summary({})).not.toEqual(queryKeys.quality.summary({}));
  });
});

describe("retry policy", () => {
  const error = (status: number) =>
    new ApiError({ kind: status === 403 ? "forbidden" : "server", status, message: "x" });

  it("does not retry a 403", () => {
    // Spec section 18: retrying an authorization failure cannot succeed and
    // only multiplies audit-log noise.
    expect(shouldRetry(0, error(403))).toBe(false);
  });

  it("retries a 500, up to the cap", () => {
    expect(shouldRetry(0, error(500))).toBe(true);
    expect(shouldRetry(1, error(500))).toBe(true);
    expect(shouldRetry(2, error(500))).toBe(false);
  });

  it("does not retry a 429", () => {
    const rateLimited = new ApiError({
      kind: "rate_limited",
      status: 429,
      message: "Slow down",
      retryAfterSeconds: 30,
    });
    // Retrying through a rate limit is how a slow backend becomes a dead one.
    expect(shouldRetry(0, rateLimited)).toBe(false);
  });

  it("does not retry an unrecognized error", () => {
    expect(shouldRetry(0, new Error("boom"))).toBe(false);
  });
});

describe("presentError", () => {
  it("offers no retry for 401, 403, 404, 422 or 429", () => {
    const noRetry = [
      "unauthorized",
      "forbidden",
      "not_found",
      "validation",
      "rate_limited",
    ] as const;
    for (const kind of noRetry) {
      const presentation = presentError(new ApiError({ kind, status: 400, message: "x" }));
      expect(presentation.canRetry, `${kind} should not offer retry`).toBe(false);
    }
  });

  it("offers retry for transport and server failures", () => {
    for (const kind of ["network", "timeout", "server"] as const) {
      expect(presentError(new ApiError({ kind, message: "x" })).canRetry).toBe(true);
    }
  });

  it("surfaces the wait from a rate limit", () => {
    const presentation = presentError(
      new ApiError({ kind: "rate_limited", status: 429, message: "x", retryAfterSeconds: 45 }),
    );
    expect(presentation.retryAfterSeconds).toBe(45);
    expect(presentation.message).toContain("45");
  });
});

describe("isBackendUnavailable", () => {
  it("is true only for transport and server failures", () => {
    expect(isBackendUnavailable(new ApiError({ kind: "network", message: "x" }))).toBe(true);
    expect(isBackendUnavailable(new ApiError({ kind: "timeout", message: "x" }))).toBe(true);
    expect(isBackendUnavailable(new ApiError({ kind: "server", message: "x" }))).toBe(true);
    // A 403 means the service answered. That is not an outage, and showing an
    // outage banner for it would misdirect the user entirely.
    expect(isBackendUnavailable(new ApiError({ kind: "forbidden", message: "x" }))).toBe(false);
    expect(isBackendUnavailable(undefined)).toBe(false);
  });
});

describe("server table pagination", () => {
  it("converts a 0-based page index to the API's 1-based page", () => {
    expect(toQueryFilters({ pagination: { pageIndex: 0, pageSize: 25 }, sorting: [] })).toEqual({
      page: 1,
      page_size: 25,
    });

    expect(toQueryFilters({ pagination: { pageIndex: 3, pageSize: 25 }, sorting: [] })).toEqual({
      page: 4,
      page_size: 25,
    });
  });

  it("sends no sort parameters when nothing is sorted", () => {
    const params = toQueryFilters({
      pagination: { pageIndex: 0, pageSize: 25 },
      sorting: [],
    });
    // An empty `sort_by` is a 422 against the backend's allow-list.
    expect(params).not.toHaveProperty("sort_by");
    expect(params).not.toHaveProperty("sort_dir");
  });

  it("sends the first sort column with a direction", () => {
    expect(
      toQueryFilters({
        pagination: { pageIndex: 0, pageSize: 25 },
        sorting: [{ id: "produced", desc: true }],
      }),
    ).toMatchObject({ sort_by: "produced", sort_dir: "desc" });
  });

  it("clamps page size to the backend's maximum", () => {
    const params = toQueryFilters({
      pagination: { pageIndex: 0, pageSize: 5_000 },
      sorting: [],
    });
    // Asking for 5,000 rows is a 422; the backend caps list responses at 100.
    expect(params.page_size).toBe(100);
  });

  it("derives control state from the backend's metadata", () => {
    const view = toPaginationView({ page: 3, page_size: 25, total: 812 });

    expect(view.pageCount).toBe(33);
    expect(view.firstRowOnPage).toBe(51);
    expect(view.lastRowOnPage).toBe(75);
    expect(view.hasPreviousPage).toBe(true);
    expect(view.hasNextPage).toBe(true);
    expect(view.label).toBe("Showing 51-75 of 812 records");
  });

  it("handles a partial last page", () => {
    const view = toPaginationView({ page: 33, page_size: 25, total: 812 });
    expect(view.lastRowOnPage).toBe(812);
    expect(view.hasNextPage).toBe(false);
  });

  it("handles an empty result and a missing envelope", () => {
    expect(toPaginationView({ page: 1, page_size: 25, total: 0 }).label).toBe("No records");
    expect(toPaginationView(undefined).rowCount).toBe(0);
  });

  it("clamps a page index that a narrowed filter left out of range", () => {
    // 39 pages of results just became 2. Without this the table sits on page 40
    // showing an empty list that reads as "no matching records".
    expect(
      clampedPageIndex({ pageIndex: 39, pageSize: 25 }, { page: 40, page_size: 25, total: 30 }),
    ).toBe(1);
  });

  it("leaves an in-range page index alone", () => {
    expect(
      clampedPageIndex({ pageIndex: 1, pageSize: 25 }, { page: 2, page_size: 25, total: 812 }),
    ).toBeNull();
  });

  it("does not clamp when the result set is empty", () => {
    // Zero results is a legitimate answer, not an out-of-range page.
    expect(
      clampedPageIndex({ pageIndex: 5, pageSize: 25 }, { page: 6, page_size: 25, total: 0 }),
    ).toBeNull();
  });
});
