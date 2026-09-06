/**
 * @vitest-environment jsdom
 */

/**
 * Navigation, the shell, and permission-aware UX (spec section 39).
 *
 * The permission test is the important one, and it asserts a *UX* property, not
 * a security one: a link the user's role cannot use is hidden so they do not
 * walk into a 403. The backend enforces the actual rule, which is why hiding
 * here is safe to do imperfectly and unsafe to rely on.
 */
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import MockAdapter from "axios-mock-adapter";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { Drawer } from "@/components/ui/Drawer";
import { apiClient } from "@/lib/api/client";
import { NAV_ITEMS, activeNavItem } from "@/lib/navigation";

let mock: MockAdapter;

beforeEach(() => {
  mock = new MockAdapter(apiClient);
});

afterEach(() => {
  mock.restore();
  vi.resetModules();
});

describe("navigation map", () => {
  it("lists the eight application areas", () => {
    expect(NAV_ITEMS.map((item) => item.href)).toEqual([
      "/dashboard",
      "/production",
      "/quality",
      "/inventory",
      "/machines",
      "/analytics",
      "/alerts",
      "/maintenance",
    ]);
  });

  it("gives every item a label and a permission", () => {
    for (const item of NAV_ITEMS) {
      // The label is the accessible name; the icon is decorative.
      expect(item.label.length).toBeGreaterThan(0);
      expect(item.permission).toMatch(/^[a-z]+:read$/);
    }
  });

  it("resolves a nested route to its parent section", () => {
    // `/machines/abc` must still highlight "Machines".
    expect(activeNavItem("/machines/abc-123")?.href).toBe("/machines");
    expect(activeNavItem("/machines")?.href).toBe("/machines");
    expect(activeNavItem("/nowhere")).toBeUndefined();
  });
});

describe("sidebar", () => {
  /**
   * The sidebar is loaded dynamically after `next/navigation` is mocked,
   * because the App Router hooks throw outside a router and the module reads
   * them at import time.
   */
  async function renderSidebar(permissions: string[]) {
    vi.doMock("next/navigation", () => ({
      usePathname: () => "/dashboard",
      useRouter: () => ({ replace: vi.fn(), push: vi.fn(), prefetch: vi.fn() }),
      useSearchParams: () => new URLSearchParams(),
    }));
    vi.doMock("@/providers/auth-provider", () => ({
      useAuth: () => ({
        state: "authenticated",
        user: null,
        isAuthenticated: true,
        isLoading: false,
        can: (permission: string) => permissions.includes(permission),
        signOut: vi.fn(),
        refresh: vi.fn(),
      }),
    }));

    const { SidebarNav } = await import("@/components/layout/Sidebar");
    return render(<SidebarNav />);
  }

  it("renders a labelled navigation landmark", async () => {
    await renderSidebar(NAV_ITEMS.map((item) => item.permission));
    expect(screen.getByRole("navigation", { name: "Main" })).toBeTruthy();
  });

  it("marks the current page with aria-current", async () => {
    await renderSidebar(NAV_ITEMS.map((item) => item.permission));
    const dashboard = screen.getByRole("link", { name: /dashboard/i });
    expect(dashboard.getAttribute("aria-current")).toBe("page");
  });

  it("hides links the role cannot use", async () => {
    await renderSidebar(["dashboard:read", "production:read"]);

    expect(screen.getByRole("link", { name: /dashboard/i })).toBeTruthy();
    expect(screen.getByRole("link", { name: /production/i })).toBeTruthy();
    // UX only: the backend refuses these regardless of what is rendered.
    expect(screen.queryByRole("link", { name: /inventory/i })).toBeNull();
    expect(screen.queryByRole("link", { name: /maintenance/i })).toBeNull();
  });

  it("shows every link while the session is still loading", async () => {
    vi.doMock("next/navigation", () => ({
      usePathname: () => "/dashboard",
      useRouter: () => ({ replace: vi.fn(), push: vi.fn(), prefetch: vi.fn() }),
      useSearchParams: () => new URLSearchParams(),
    }));
    vi.doMock("@/providers/auth-provider", () => ({
      useAuth: () => ({
        state: "loading",
        user: null,
        isAuthenticated: false,
        isLoading: true,
        can: () => false,
        signOut: vi.fn(),
        refresh: vi.fn(),
      }),
    }));

    const { SidebarNav } = await import("@/components/layout/Sidebar");
    render(<SidebarNav />);

    // Better than flashing a two-item menu that grows a moment later.
    expect(screen.getAllByRole("link")).toHaveLength(NAV_ITEMS.length);
  });
});

describe("responsive drawer", () => {
  it("renders nothing when closed", () => {
    const { container } = render(
      <Drawer open={false} onClose={vi.fn()} title="Navigation">
        <a href="/dashboard">Dashboard</a>
      </Drawer>,
    );
    expect(container.firstChild).toBeNull();
  });

  it("is a labelled modal dialog when open", () => {
    render(
      <Drawer open onClose={vi.fn()} title="Navigation">
        <a href="/dashboard">Dashboard</a>
      </Drawer>,
    );

    const dialog = screen.getByRole("dialog");
    expect(dialog.getAttribute("aria-modal")).toBe("true");
    expect(screen.getByRole("heading", { name: "Navigation" })).toBeTruthy();
  });

  it("closes on Escape", async () => {
    const onClose = vi.fn();
    render(
      <Drawer open onClose={onClose} title="Navigation">
        <a href="/dashboard">Dashboard</a>
      </Drawer>,
    );

    // The only exit for a keyboard user who cannot reach the close button.
    fireEvent.keyDown(document, { key: "Escape" });
    await waitFor(() => expect(onClose).toHaveBeenCalledTimes(1));
  });

  it("has a named close button", () => {
    render(
      <Drawer open onClose={vi.fn()} title="Navigation">
        <a href="/dashboard">Dashboard</a>
      </Drawer>,
    );
    expect(screen.getByRole("button", { name: "Close menu" })).toBeTruthy();
  });

  it("locks background scrolling while open", () => {
    const { unmount } = render(
      <Drawer open onClose={vi.fn()} title="Navigation">
        <a href="/dashboard">Dashboard</a>
      </Drawer>,
    );

    expect(document.body.style.overflow).toBe("hidden");
    unmount();
    expect(document.body.style.overflow).not.toBe("hidden");
  });
});
