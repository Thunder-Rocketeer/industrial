/**
 * @vitest-environment jsdom
 */

/**
 * Query hooks: the five view states, and what a component actually sees
 * (spec section 31).
 *
 * These render the real hooks against a real QueryClient with the Axios adapter
 * stubbed, so the assertions cover the whole path -- key, request, envelope
 * unwrapping, error normalization and state derivation -- rather than a mocked
 * middle.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import MockAdapter from "axios-mock-adapter";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { useActiveAlerts } from "@/hooks/queries/useAlerts";
import { useMachines } from "@/hooks/queries/useMachines";
import { useProductionRecords } from "@/hooks/queries/useProduction";
import { apiClient } from "@/lib/api/client";

let mock: MockAdapter;

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({
    defaultOptions: {
      // Retries off: a test asserting the error state should not wait out an
      // exponential backoff to reach it.
      queries: { retry: false, gcTime: 0 },
    },
  });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

beforeEach(() => {
  mock = new MockAdapter(apiClient);
});

afterEach(() => {
  mock.restore();
});

describe("query state", () => {
  it("starts in loading with no data", async () => {
    mock.onGet("/machines").reply(200, { data: [] });

    const { result } = renderHook(() => useMachines(), { wrapper });

    expect(result.current.status).toBe("loading");
    expect(result.current.isLoading).toBe(true);
    expect(result.current.data).toBeUndefined();

    await waitFor(() => expect(result.current.isLoading).toBe(false));
  });

  it("reaches success with the unwrapped payload", async () => {
    mock.onGet("/machines").reply(200, { data: [{ id: "1", code: "MOCK-1" }] });

    const { result } = renderHook(() => useMachines(), { wrapper });

    await waitFor(() => expect(result.current.status).toBe("success"));
    expect(result.current.data).toHaveLength(1);
    expect(result.current.error).toBeUndefined();
  });

  it("reports empty separately from success", async () => {
    mock.onGet("/machines").reply(200, { data: [] });

    const { result } = renderHook(() => useMachines(), { wrapper });

    // A successful request with no rows is neither an error nor a loading
    // state, and a table rendered with headers and no explanation looks broken.
    await waitFor(() => expect(result.current.status).toBe("empty"));
    expect(result.current.isEmpty).toBe(true);
    expect(result.current.isSuccess).toBe(false);
    expect(result.current.data).toEqual([]);
  });

  it("treats an empty page of a paginated list as empty", async () => {
    mock.onGet("/production").reply(200, {
      data: [],
      pagination: { page: 1, page_size: 25, total: 0 },
    });

    const { result } = renderHook(() => useProductionRecords(), { wrapper });

    await waitFor(() => expect(result.current.status).toBe("empty"));
    // The envelope is still there: the table needs the metadata even when the
    // page has no rows.
    expect(result.current.data?.pagination.total).toBe(0);
  });

  it("exposes a normalized error, not an Axios error", async () => {
    mock.onGet("/machines").reply(403, {
      error: { code: "FORBIDDEN", message: "Insufficient permissions" },
    });

    const { result } = renderHook(() => useMachines(), { wrapper });

    await waitFor(() => expect(result.current.status).toBe("error"));
    expect(result.current.error?.kind).toBe("forbidden");
    expect(result.current.error?.status).toBe(403);
  });

  it("refetches on demand and keeps data visible while it does", async () => {
    mock.onGet("/alerts/active").replyOnce(200, { data: [{ id: "1" }] });

    const { result } = renderHook(() => useActiveAlerts(), { wrapper });
    await waitFor(() => expect(result.current.status).toBe("success"));

    // Deliberately slow, so the in-flight window is observable. With an
    // instant reply the refresh resolves inside the same tick and the state
    // this test exists to check is never rendered.
    mock.onGet("/alerts/active").reply(
      () =>
        new Promise((resolve) => {
          setTimeout(() => resolve([200, { data: [{ id: "1" }, { id: "2" }] }]), 50);
        }),
    );
    result.current.refetch();

    // Spec section 20: a refetch must not blank the screen. The previous data
    // stays readable while the new request is in flight.
    await waitFor(() => expect(result.current.isRefreshing).toBe(true));
    expect(result.current.data).toBeDefined();
    expect(result.current.isLoading).toBe(false);

    await waitFor(() => expect(result.current.data).toHaveLength(2));
  });

  it("does not request anything while a detail query is disabled", async () => {
    // `enabled: Boolean(id)` -- the guard that stops a page from requesting
    // `/machines/undefined` on its first render.
    const { result } = renderHook(() => useMachines({}, { enabled: false }), {
      wrapper,
    });

    expect(mock.history.get).toHaveLength(0);
    expect(result.current.status).toBe("loading");
  });
});

describe("filters and cache keys", () => {
  it("sends the hook's filters as query parameters", async () => {
    mock.onGet("/production").reply(200, {
      data: [],
      pagination: { page: 1, page_size: 25, total: 0 },
    });

    renderHook(() => useProductionRecords({ page: 2, sort_by: "produced" }), {
      wrapper,
    });

    await waitFor(() => expect(mock.history.get).toHaveLength(1));
    expect(mock.history.get[0].params).toMatchObject({
      page: 2,
      sort_by: "produced",
    });
  });

  it("does not refetch when a filter changes only by an undefined key", async () => {
    mock.onGet("/machines").reply(200, { data: [{ id: "1" }] });

    const { rerender, result } = renderHook(
      ({ status }: { status?: "RUNNING" }) => useMachines({ status }),
      { wrapper, initialProps: {} },
    );

    await waitFor(() => expect(result.current.status).toBe("success"));
    expect(mock.history.get).toHaveLength(1);

    // `{}` and `{ status: undefined }` are the same request. Normalized keys
    // are what stop this from being a second one.
    rerender({ status: undefined });
    await waitFor(() => expect(result.current.status).toBe("success"));
    expect(mock.history.get).toHaveLength(1);
  });
});
