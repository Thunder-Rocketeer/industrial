/**
 * @vitest-environment jsdom
 */

/**
 * Structural accessibility checks (spec sections 18 and 38).
 *
 * These render the real dashboard against stubbed HTTP and assert the
 * properties that a screen reader, a keyboard, and the accessibility tree
 * depend on. They are not a substitute for testing with an actual screen
 * reader, and they are not claimed to be: what they catch is the class of
 * regression that is invisible in a browser — a skipped heading level, a button
 * with no accessible name, a duplicate id — and that nobody notices until
 * someone tries to use the page without a mouse.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import MockAdapter from "axios-mock-adapter";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { apiClient } from "@/lib/api/client";
import {
  mockAlertSummary,
  mockAlerts,
  mockDashboardSummary,
  mockInventorySummary,
  mockMachineFleetSummary,
  mockOee,
  mockProductionSummary,
  mockQualitySummary,
} from "@/lib/api/mock/fixtures";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: vi.fn(), push: vi.fn(), prefetch: vi.fn() }),
  usePathname: () => "/dashboard",
  useSearchParams: () => new URLSearchParams(),
}));

const { DashboardView } = await import("@/app/(app)/dashboard/DashboardView");

let mock: MockAdapter;

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

/**
 * A complete dashboard response, assembled from the development fixtures so
 * the shapes stay in step with the types.
 */
const summary = {
  ...mockDashboardSummary,
  kpis: [
    {
      key: "production",
      label: "Production",
      value: 9250,
      unit: "units",
      context_label: "92.5% of target",
      status: "warning" as const,
      status_label: "Below target",
      trend: { change_percentage: 4.2, direction: "up" as const, comparison_label: "vs yesterday" },
    },
    {
      key: "oee",
      label: "OEE",
      value: 74,
      unit: "%",
      context_label: "Availability is lowest",
      status: "warning" as const,
      status_label: "Below target",
      trend: {
        change_percentage: null,
        direction: "unknown" as const,
        comparison_label: "vs yesterday",
      },
    },
  ],
  production: mockProductionSummary,
  quality: mockQualitySummary,
  inventory: mockInventorySummary,
  machines: mockMachineFleetSummary,
  oee: mockOee,
  alerts: mockAlertSummary,
  recent_alerts: mockAlerts,
};

const trends = {
  start_date: "2026-01-01",
  end_date: "2026-01-15",
  production: [
    {
      bucket_date: "2026-01-01",
      planned_quantity: 1000,
      produced_quantity: 900,
      accepted_quantity: 880,
      rejected_quantity: 20,
      target_quantity: 950,
      achievement_percentage: 94.7,
    },
  ],
  defects: [],
  oee: [],
  top_defects: [
    {
      defect_id: "d1",
      defect_code: "D1",
      defect_name: "Surface finish",
      category: "Finishing",
      default_severity: "MAJOR" as const,
      rejected_quantity: 500,
      occurrence_count: 40,
      share_percentage: 62.5,
      cumulative_percentage: 62.5,
    },
  ],
  has_data: true,
};

beforeEach(() => {
  mock = new MockAdapter(apiClient);
  mock.onGet("/dashboard/summary").reply(200, { data: summary });
  mock.onGet("/dashboard/trends").reply(200, { data: trends });
});

afterEach(() => {
  mock.restore();
});

async function renderDashboard() {
  const result = render(<DashboardView />, { wrapper });
  await waitFor(() => expect(screen.getByText("9,250")).toBeTruthy());
  return result;
}

describe("dashboard structure", () => {
  it("has exactly one h1", async () => {
    await renderDashboard();
    const h1s = screen.getAllByRole("heading", { level: 1 });
    expect(h1s).toHaveLength(1);
    expect(h1s[0].textContent).toBe("Factory Operations");
  });

  it("never skips a heading level", async () => {
    const { container } = await renderDashboard();
    const levels = [...container.querySelectorAll("h1,h2,h3,h4,h5,h6")].map((element) =>
      Number(element.tagName[1]),
    );

    expect(levels[0]).toBe(1);
    // A real page, not an error state: the dashboard renders a dozen headings.
    expect(levels.length).toBeGreaterThan(8);
    for (let index = 1; index < levels.length; index += 1) {
      // A jump from h2 to h4 breaks the outline a screen-reader user navigates
      // by (WCAG 1.3.1).
      expect(
        levels[index] - levels[index - 1],
        `heading ${index} jumps from h${levels[index - 1]} to h${levels[index]}`,
      ).toBeLessThanOrEqual(1);
    }
  });

  it("gives every section a heading", async () => {
    const { container } = await renderDashboard();
    const sections = [...container.querySelectorAll("section")];
    expect(sections.length).toBeGreaterThan(3);

    for (const section of sections) {
      const hasHeading = section.querySelector("h2,h3,h4") !== null;
      const hasLabel =
        section.hasAttribute("aria-labelledby") || section.hasAttribute("aria-label");
      expect(hasHeading || hasLabel).toBe(true);
    }
  });

  it("gives every button an accessible name", async () => {
    const { container } = await renderDashboard();
    for (const button of container.querySelectorAll("button")) {
      const name =
        button.getAttribute("aria-label") ??
        button.getAttribute("title") ??
        button.textContent?.trim();
      // A button announced as just "button" is unusable (WCAG 4.1.2).
      expect(
        name,
        `a button has no accessible name: ${button.outerHTML.slice(0, 90)}`,
      ).toBeTruthy();
    }
  });

  it("gives every link an accessible name", async () => {
    const { container } = await renderDashboard();
    for (const link of container.querySelectorAll("a")) {
      const name = link.getAttribute("aria-label") ?? link.textContent?.trim();
      expect(name, `a link has no accessible name: ${link.outerHTML.slice(0, 90)}`).toBeTruthy();
    }
  });

  it("emits no duplicate element ids", async () => {
    const { container } = await renderDashboard();
    const ids = [...container.querySelectorAll("[id]")].map((element) => element.id);
    // A duplicate breaks every aria-labelledby and label-for that points at it.
    expect(new Set(ids).size).toBe(ids.length);
  });

  it("gives every image an alt attribute", async () => {
    const { container } = await renderDashboard();
    for (const image of container.querySelectorAll("img")) {
      expect(image.hasAttribute("alt")).toBe(true);
    }
  });

  it("marks decorative icons aria-hidden", async () => {
    const { container } = await renderDashboard();
    const svgs = [...container.querySelectorAll("svg")];
    expect(svgs.length).toBeGreaterThan(0);

    for (const svg of svgs) {
      const labelled = svg.getAttribute("role") === "img" && svg.hasAttribute("aria-label");
      const hidden = svg.getAttribute("aria-hidden") === "true";
      // Either it is named, or it is hidden. Never an unnamed exposed graphic.
      expect(labelled || hidden).toBe(true);
    }
  });
});

describe("dashboard status communication", () => {
  it("renders every KPI status as text", async () => {
    await renderDashboard();
    // Spec section 4 / WCAG 1.4.1: never colour alone.
    expect(screen.getAllByText("Below target").length).toBeGreaterThanOrEqual(2);
  });

  it("states the alert count in words in the banner", async () => {
    await renderDashboard();
    expect(screen.getByText(/open/)).toBeTruthy();
    expect(screen.getAllByText(/Critical/).length).toBeGreaterThan(0);
  });

  it("gives the status distribution bars a text alternative", async () => {
    await renderDashboard();
    const bars = screen.getAllByRole("img");
    const labels = bars.map((bar) => bar.getAttribute("aria-label") ?? "");
    // The machine fleet bar names each segment and its count.
    expect(labels.some((label) => /machines:.*Running/.test(label))).toBe(true);
  });

  it("gives charts a visually hidden text summary", async () => {
    const { container } = await renderDashboard();
    const figures = [...container.querySelectorAll("figure")];
    expect(figures.length).toBeGreaterThan(0);

    for (const figure of figures) {
      const caption = figure.querySelector("figcaption");
      expect(caption?.textContent?.length ?? 0).toBeGreaterThan(20);
      // WCAG 1.1.1: the equivalent for a non-text element.
      expect(caption?.className).toContain("sr-only");
    }
  });

  it("offers the chart data as a real table", async () => {
    const { container } = await renderDashboard();
    const details = [...container.querySelectorAll("details")];
    expect(details.length).toBeGreaterThan(0);
    expect(details[0].querySelector("table")).toBeTruthy();
    expect(details[0].querySelectorAll("th[scope=col]").length).toBeGreaterThan(0);
  });
});

describe("dashboard loading and error announcement", () => {
  it("announces the loading state rather than rendering silence", () => {
    render(<DashboardView />, { wrapper });
    // Before data arrives, a screen-reader user is told work is happening.
    const statuses = screen.getAllByRole("status");
    expect(statuses.length).toBeGreaterThan(0);
    expect(statuses.some((element) => element.getAttribute("aria-busy") === "true")).toBe(true);
  });

  it("announces a failure with role=alert", async () => {
    mock.reset();
    mock.onGet("/dashboard/summary").reply(500, {
      error: { code: "INTERNAL_ERROR", message: "Unexpected error" },
    });
    mock.onGet("/dashboard/trends").reply(500, {
      error: { code: "INTERNAL_ERROR", message: "Unexpected error" },
    });

    render(<DashboardView />, { wrapper });

    await waitFor(() => expect(screen.getAllByRole("alert").length).toBeGreaterThan(0));
  });
});
