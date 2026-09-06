/**
 * Filter serialization (spec section 31).
 *
 * `buildParams` decides what actually reaches the backend as a query string.
 * The cases that matter are the ones where a value should *disappear*: an
 * untouched filter must not be sent, because `?machine_id=` is a validation
 * error on a UUID field, and the user sees "those filters are not valid" for a
 * filter they never set.
 */
import { describe, expect, it } from "vitest";

import { buildParams, normalizeFilters, toIsoDate } from "@/lib/api/params";

describe("buildParams", () => {
  it("returns an empty object when there are no filters", () => {
    expect(buildParams(undefined)).toEqual({});
    expect(buildParams({})).toEqual({});
  });

  it("drops undefined and null so cleared filters are not sent", () => {
    expect(buildParams({ machine_id: undefined, component_id: null, page: 2 })).toEqual({
      page: 2,
    });
  });

  it("drops empty and whitespace-only strings", () => {
    // A select reset to its placeholder yields "", which as `?status=` is a 422
    // against an enum field rather than "no filter".
    expect(buildParams({ status: "", search: "   ", sku: "MOCK-1" })).toEqual({
      sku: "MOCK-1",
    });
  });

  it("trims strings that are kept", () => {
    expect(buildParams({ sku: "  ABC-1  " })).toEqual({ sku: "ABC-1" });
  });

  it("keeps zero and false, which are meaningful values", () => {
    // `0` and `false` are falsy but not absent: `upcoming_only=false` is a real
    // request, and a truthiness check here would silently drop both.
    expect(buildParams({ page: 0, upcoming_only: false })).toEqual({
      page: 0,
      upcoming_only: false,
    });
  });

  it("drops NaN rather than sending 'NaN'", () => {
    // Number("") is NaN, which a parseInt on an emptied number input produces.
    expect(buildParams({ page_size: Number.NaN, page: 1 })).toEqual({ page: 1 });
  });

  it("formats Date values as ISO dates", () => {
    expect(buildParams({ start_date: new Date(Date.UTC(2026, 0, 5)) })).toEqual({
      start_date: "2026-01-05",
    });
  });

  it("keeps arrays and drops empty ones", () => {
    expect(buildParams({ shift: ["A", "B"], line: [] })).toEqual({
      shift: ["A", "B"],
    });
  });

  it("drops values it cannot serialize instead of coercing them", () => {
    // Without this, an object reaches the wire as "[object Object]" -- a query
    // parameter that is syntactically fine and semantically nonsense.
    expect(buildParams({ nested: { a: 1 }, page: 1 })).toEqual({ page: 1 });
  });
});

describe("normalizeFilters", () => {
  it("produces the same result for absent and undefined keys", () => {
    // This is what keeps `{page: 1}` and `{page: 1, machine_id: undefined}` on
    // one cache entry instead of two.
    expect(normalizeFilters({ page: 1 })).toEqual(
      normalizeFilters({ page: 1, machine_id: undefined }),
    );
  });
});

describe("toIsoDate", () => {
  it("formats in UTC, not the local timezone", () => {
    // 23:00 UTC on 5 Jan is still 5 Jan. A local-time formatter would return
    // the 6th east of UTC, shifting every date filter by a day.
    expect(toIsoDate(new Date(Date.UTC(2026, 0, 5, 23, 0, 0)))).toBe("2026-01-05");
  });
});
