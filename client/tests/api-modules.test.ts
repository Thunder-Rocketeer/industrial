/**
 * API modules: what they request, and what they send with it (spec section 31).
 *
 * These assert against the request the shared Axios client actually issues, not
 * against a stubbed function, so a wrong path or a dropped filter is caught
 * here rather than as an empty panel in the browser.
 */
import MockAdapter from "axios-mock-adapter";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { fetchActiveAlerts, fetchAlerts } from "@/lib/api/alerts";
import { apiClient } from "@/lib/api/client";
import { fetchDashboardSummary } from "@/lib/api/dashboard";
import { fetchInventoryItems } from "@/lib/api/inventory";
import { fetchMachine, fetchMachines } from "@/lib/api/machines";
import { fetchProductionRecords, fetchProductionSummary } from "@/lib/api/production";

let mock: MockAdapter;

beforeEach(() => {
  mock = new MockAdapter(apiClient);
});

afterEach(() => {
  mock.restore();
});

describe("response envelopes", () => {
  it("unwraps the data envelope for single-resource responses", async () => {
    mock.onGet("/production/summary").reply(200, { data: { total_produced: 42 } });

    const summary = await fetchProductionSummary();

    // The caller gets the payload, not `{ data: ... }`.
    expect(summary).toEqual({ total_produced: 42 });
  });

  it("returns the whole paginated envelope for list responses", async () => {
    const body = {
      data: [{ id: "1" }],
      pagination: { page: 2, page_size: 25, total: 812 },
    };
    mock.onGet("/production").reply(200, body);

    const page = await fetchProductionRecords({ page: 2 });

    // The pagination metadata is what a table needs to render controls, so it
    // is deliberately not unwrapped away.
    expect(page).toEqual(body);
    expect(page.pagination.total).toBe(812);
  });
});

describe("request construction", () => {
  it("sends filters as Axios query parameters, not a concatenated string", async () => {
    mock.onGet("/production").reply(200, {
      data: [],
      pagination: { page: 1, page_size: 25, total: 0 },
    });

    await fetchProductionRecords({
      start_date: "2026-01-01",
      end_date: "2026-01-31",
      machine_id: "00000000-0000-4000-8000-000000000001",
      page: 1,
    });

    const request = mock.history.get[0];
    // The URL carries no "?" of its own: Axios owns the serialization, so
    // values are escaped rather than pasted in (spec section 15).
    expect(request.url).toBe("/production");
    expect(request.params).toEqual({
      start_date: "2026-01-01",
      end_date: "2026-01-31",
      machine_id: "00000000-0000-4000-8000-000000000001",
      page: 1,
    });
  });

  it("omits filters that were never set", async () => {
    mock.onGet("/alerts").reply(200, {
      data: [],
      pagination: { page: 1, page_size: 25, total: 0 },
    });

    await fetchAlerts({ severity: undefined, status: "OPEN" });

    expect(mock.history.get[0].params).toEqual({ status: "OPEN" });
  });

  it("interpolates a path id and still passes filters as parameters", async () => {
    const id = "00000000-0000-4000-8000-000000000001";
    mock.onGet(`/machines/${id}`).reply(200, { data: { id } });

    await fetchMachine(id, { start_date: "2026-01-01" });

    expect(mock.history.get[0].url).toBe(`/machines/${id}`);
    expect(mock.history.get[0].params).toEqual({ start_date: "2026-01-01" });
  });

  it("sends the credentials the session cookie needs", async () => {
    mock.onGet("/dashboard/summary").reply(200, { data: {} });

    await fetchDashboardSummary();

    // Without this the HttpOnly session cookie is not attached and every
    // request is anonymous (spec section 55.3).
    expect(mock.history.get[0].withCredentials).toBe(true);
  });

  it("attaches a correlation id to every request", async () => {
    mock.onGet("/machines").reply(200, { data: [] });

    await fetchMachines();

    const headers = mock.history.get[0].headers ?? {};
    expect(headers["X-Request-ID"]).toBeTruthy();
  });

  it("passes an explicit limit through", async () => {
    mock.onGet("/alerts/active").reply(200, { data: [] });

    await fetchActiveAlerts(5);

    expect(mock.history.get[0].params).toEqual({ limit: 5 });
  });

  it("sends no parameters when a limit is not given", async () => {
    mock.onGet("/alerts/active").reply(200, { data: [] });

    await fetchActiveAlerts();

    expect(mock.history.get[0].params ?? {}).toEqual({});
  });
});

describe("error normalization", () => {
  it("normalizes a 403 into a forbidden ApiError", async () => {
    mock.onGet("/inventory").reply(403, {
      error: { code: "FORBIDDEN", message: "Insufficient permissions" },
    });

    await expect(fetchInventoryItems()).rejects.toMatchObject({
      kind: "forbidden",
      status: 403,
      isRetryable: false,
      // Not an auth error: the session is valid, the role is not sufficient.
      // Signing in again changes nothing, so nothing should prompt for it.
      isAuthError: false,
    });
  });

  it("normalizes a 422 and keeps the field details", async () => {
    mock.onGet("/production").reply(422, {
      error: {
        code: "VALIDATION_ERROR",
        message: "Invalid filters",
        details: { sort_by: ["not an allowed sort key"] },
      },
    });

    await expect(fetchProductionRecords()).rejects.toMatchObject({
      kind: "validation",
      status: 422,
      isRetryable: false,
      details: { sort_by: ["not an allowed sort key"] },
    });
  });

  it("normalizes a 429 and reads Retry-After", async () => {
    mock.onGet("/dashboard/summary").reply(
      429,
      { error: { code: "RATE_LIMITED", message: "Slow down" } },
      {
        "retry-after": "30",
      },
    );

    await expect(fetchDashboardSummary()).rejects.toMatchObject({
      kind: "rate_limited",
      // Not retryable automatically: the server said how long to wait, and
      // ignoring that is what turns a rate limit into an outage.
      isRetryable: false,
      retryAfterSeconds: 30,
    });
  });

  it("normalizes a network failure", async () => {
    mock.onGet("/machines").networkError();

    await expect(fetchMachines()).rejects.toMatchObject({
      kind: "network",
      // Worth retrying: nothing reached the server, so nothing was applied.
      isRetryable: true,
    });
  });

  it("normalizes a 500 as retryable", async () => {
    mock.onGet("/machines").reply(500, {
      error: { code: "INTERNAL_ERROR", message: "Unexpected error" },
    });

    await expect(fetchMachines()).rejects.toMatchObject({
      kind: "server",
      status: 500,
      isRetryable: true,
    });
  });

  it("never exposes a raw Axios error to callers", async () => {
    mock.onGet("/machines").reply(500, { error: { code: "X", message: "y" } });

    // An unnormalized error would carry `config.headers` -- including the
    // session cookie in some environments -- into component code and logs.
    await expect(fetchMachines()).rejects.not.toHaveProperty("config");
  });
});
