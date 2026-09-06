/**
 * @vitest-environment jsdom
 */

/**
 * The authenticated UI: user display, logout, and session expiry
 * (spec sections 30, 31 and 39).
 *
 * The recurring assertion is a negative one: nothing in this UI derives from a
 * token, because there is no token in the browser to derive from. Every field
 * shown comes from `GET /auth/me`.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import MockAdapter from "axios-mock-adapter";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { apiClient } from "@/lib/api/client";
import { TEST_USER } from "./helpers";

const replace = vi.fn();

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace, push: vi.fn(), prefetch: vi.fn(), refresh: vi.fn() }),
  usePathname: () => "/dashboard",
  useSearchParams: () => new URLSearchParams(),
}));

const { AuthProvider } = await import("@/providers/auth-provider");
const { UserMenu } = await import("@/components/layout/UserMenu");
const { SessionExpiryWatcher } = await import("@/providers/session-expiry-watcher");
const { onSessionExpired } = await import("@/lib/api/client");

let mock: MockAdapter;

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  });
  return (
    <QueryClientProvider client={client}>
      <AuthProvider>{children}</AuthProvider>
    </QueryClientProvider>
  );
}

beforeEach(() => {
  mock = new MockAdapter(apiClient);
  replace.mockClear();
});

afterEach(() => {
  mock.restore();
});

describe("user display", () => {
  it("shows the signed-in user's name and role", async () => {
    mock.onGet("/auth/me").reply(200, { data: TEST_USER });

    render(<UserMenu />, { wrapper });

    await waitFor(() => expect(screen.getByText("Priya Raman")).toBeTruthy());
    // The backend's `role_label`, not a lookup table in the UI.
    expect(screen.getAllByText("Factory Manager").length).toBeGreaterThan(0);
  });

  it("shows the email only inside the opened menu", async () => {
    mock.onGet("/auth/me").reply(200, { data: TEST_USER });
    render(<UserMenu />, { wrapper });
    await waitFor(() => expect(screen.getByText("Priya Raman")).toBeTruthy());

    expect(screen.queryByText("manager@factory.test")).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: /account menu/i }));
    expect(screen.getByText("manager@factory.test")).toBeTruthy();
  });

  it("gives the trigger an accessible name", async () => {
    mock.onGet("/auth/me").reply(200, { data: TEST_USER });
    render(<UserMenu />, { wrapper });

    await waitFor(() =>
      expect(screen.getByRole("button", { name: /account menu for Priya Raman/i })).toBeTruthy(),
    );
  });

  it("renders nothing for an anonymous visitor", async () => {
    mock.onGet("/auth/me").reply(401, {
      error: { code: "UNAUTHENTICATED", message: "Not authenticated" },
    });

    const { container } = render(<UserMenu />, { wrapper });
    await waitFor(() => expect(container.firstChild).toBeNull());
  });

  it("exposes no token or JWT content anywhere in the markup", async () => {
    mock.onGet("/auth/me").reply(200, { data: TEST_USER });
    const { container } = render(<UserMenu />, { wrapper });
    await waitFor(() => expect(screen.getByText("Priya Raman")).toBeTruthy());

    fireEvent.click(screen.getByRole("button", { name: /account menu/i }));

    const html = container.innerHTML;
    // Spec section 30: do not expose JWT contents.
    expect(html).not.toMatch(/eyJ[A-Za-z0-9_-]/); // a JWT header, base64url
    expect(html.toLowerCase()).not.toContain("bearer ");
    expect(html).not.toContain("acf_session");
  });
});

describe("logout", () => {
  it("calls the API with a CSRF token and returns to login", async () => {
    mock.onGet("/auth/me").reply(200, { data: TEST_USER });
    mock.onGet("/auth/csrf").reply(200, { data: { csrf_token: "csrf-value" } });
    mock.onPost("/auth/logout").reply(200, { data: { logged_out: true, session_revoked: true } });

    render(<UserMenu />, { wrapper });
    await waitFor(() => expect(screen.getByText("Priya Raman")).toBeTruthy());

    fireEvent.click(screen.getByRole("button", { name: /account menu/i }));
    fireEvent.click(screen.getByRole("menuitem", { name: /sign out/i }));

    await waitFor(() => expect(mock.history.post.length).toBe(1));
    expect(mock.history.post[0].headers?.["X-CSRF-Token"]).toBe("csrf-value");
    await waitFor(() => expect(replace).toHaveBeenCalledWith("/login"));
  });

  it("still signs out locally when the API call fails", async () => {
    mock.onGet("/auth/me").reply(200, { data: TEST_USER });
    mock.onGet("/auth/csrf").reply(401, {
      error: { code: "UNAUTHENTICATED", message: "Session expired" },
    });

    render(<UserMenu />, { wrapper });
    await waitFor(() => expect(screen.getByText("Priya Raman")).toBeTruthy());

    fireEvent.click(screen.getByRole("button", { name: /account menu/i }));
    fireEvent.click(screen.getByRole("menuitem", { name: /sign out/i }));

    // The usual cause is an already-expired token, where the server has nothing
    // left to revoke. Refusing to sign out would trap the user.
    await waitFor(() => expect(replace).toHaveBeenCalledWith("/login"));
  });
});

describe("session expiry", () => {
  it("clears the cache and redirects with a reason", async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    client.setQueryData(["production", "list", {}], { data: ["secret"] });

    render(
      <QueryClientProvider client={client}>
        <SessionExpiryWatcher />
      </QueryClientProvider>,
    );

    // Drive the real notification path rather than calling an internal.
    mock.onGet("/machines").reply(401, {
      error: { code: "UNAUTHENTICATED", message: "Session expired" },
    });
    const { fetchMachines } = await import("@/lib/api/machines");

    // The suppression window is module-level; move past any earlier test's.
    vi.spyOn(Date, "now").mockReturnValue(Date.now() + 60_000);
    await expect(fetchMachines()).rejects.toMatchObject({ kind: "unauthorized" });

    await waitFor(() =>
      expect(replace).toHaveBeenCalledWith(
        expect.stringContaining("/login?next=") as unknown as string,
      ),
    );
    // Nothing fetched as the previous user survives into the next session.
    expect(client.getQueryData(["production", "list", {}])).toBeUndefined();

    const target = replace.mock.calls.at(-1)?.[0] as string;
    expect(target).toContain("reason=auth_failed");
    vi.restoreAllMocks();
  });

  it("registers and unregisters its listener cleanly", () => {
    const handler = vi.fn();
    const unsubscribe = onSessionExpired(handler);
    expect(typeof unsubscribe).toBe("function");
    unsubscribe();
  });
});
