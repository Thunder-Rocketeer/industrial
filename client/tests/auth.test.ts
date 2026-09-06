/**
 * @vitest-environment jsdom
 */

/**
 * How the data layer interacts with authentication (spec section 31).
 *
 * Phase 5 does not implement authentication -- Phase 4 did. These tests pin the
 * contract between the two so a later change to the data layer cannot quietly
 * break it: the cookie travels on its own, a 401 announces expiry exactly once,
 * and the session probe is exempt.
 */
import MockAdapter from "axios-mock-adapter";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { fetchCurrentUser, logout } from "@/lib/api/auth";
import { apiClient, onSessionExpired } from "@/lib/api/client";
import { fetchMachines } from "@/lib/api/machines";

let mock: MockAdapter;

beforeEach(() => {
  mock = new MockAdapter(apiClient);
});

afterEach(() => {
  mock.restore();
  vi.useRealTimers();
});

describe("authenticated requests", () => {
  it("sends credentials and no Authorization header", async () => {
    mock.onGet("/machines").reply(200, { data: [] });

    await fetchMachines();

    const request = mock.history.get[0];
    // The session is an HttpOnly cookie the browser attaches itself. There is
    // deliberately no Authorization header, because building one would require
    // a token readable by JavaScript (spec section 55.3).
    expect(request.withCredentials).toBe(true);
    const headers = request.headers ?? {};
    expect(headers["Authorization"]).toBeUndefined();
    expect(headers["authorization"]).toBeUndefined();
  });

  it("sends a CSRF token on a state-changing request", async () => {
    mock.onGet("/auth/csrf").reply(200, { data: { csrf_token: "csrf-value" } });
    mock.onPost("/auth/logout").reply(200, { data: { success: true } });

    await logout();

    expect(mock.history.post[0].headers?.["X-CSRF-Token"]).toBe("csrf-value");
  });
});

describe("session expiry", () => {
  it("notifies once when a request returns 401", async () => {
    const handler = vi.fn();
    const unsubscribe = onSessionExpired(handler);

    mock.onGet("/machines").reply(401, {
      error: { code: "UNAUTHENTICATED", message: "Session expired" },
    });

    await expect(fetchMachines()).rejects.toMatchObject({ kind: "unauthorized" });
    expect(handler).toHaveBeenCalledTimes(1);

    unsubscribe();
  });

  it("suppresses the burst when several requests fail at once", async () => {
    const handler = vi.fn();
    const unsubscribe = onSessionExpired(handler);

    // The suppression window is module-level state with a five-second life, so
    // the previous test's notification is still inside it. Moving the clock
    // past that window isolates this test from the order it runs in -- and
    // holding `now` fixed is what makes the burst a burst.
    const now = Date.now() + 10_000;
    vi.spyOn(Date, "now").mockReturnValue(now);

    mock.onGet(/.*/).reply(401, {
      error: { code: "UNAUTHENTICATED", message: "Session expired" },
    });

    // A dashboard fires many requests together. Without suppression each 401
    // would trigger its own redirect (spec section 27).
    await Promise.allSettled([fetchMachines(), fetchMachines(), fetchMachines()]);

    expect(handler).toHaveBeenCalledTimes(1);
    unsubscribe();
  });

  it("does not announce expiry for the session probe", async () => {
    const handler = vi.fn();
    const unsubscribe = onSessionExpired(handler);

    mock.onGet("/auth/me").reply(401, {
      error: { code: "UNAUTHENTICATED", message: "Not authenticated" },
    });

    // A 401 here is the normal answer for an anonymous visitor. Treating it as
    // an expiry would make every signed-out page load claim a session ended.
    await expect(fetchCurrentUser()).rejects.toMatchObject({ kind: "unauthorized" });
    expect(handler).not.toHaveBeenCalled();

    unsubscribe();
  });

  it("stops notifying after unsubscribe", async () => {
    const handler = vi.fn();
    onSessionExpired(handler)();

    mock.onGet("/machines").reply(401, {
      error: { code: "UNAUTHENTICATED", message: "Session expired" },
    });

    await expect(fetchMachines()).rejects.toMatchObject({ kind: "unauthorized" });
    expect(handler).not.toHaveBeenCalled();
  });
});
