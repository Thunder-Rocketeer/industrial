/**
 * @vitest-environment jsdom
 */

/**
 * Dashboard rendering: KPIs, and the loading / error / empty states
 * (spec section 39).
 *
 * These mount real components against stubbed HTTP, so they cover what a user
 * actually meets: the value on the card, the word beside it, and the accessible
 * sentence a screen reader would read.
 */
import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { AlertRow } from "@/components/dashboard/AlertsPanel";
import { OeeBreakdown, StatusDistribution, TargetVsActual } from "@/components/dashboard/Gauges";
import { KpiCard } from "@/components/dashboard/KpiCard";
import { QueryBoundary } from "@/components/data/QueryBoundary";
import { ApiError } from "@/lib/api/errors";
import type { QueryState } from "@/lib/query/query-state";
import type { Alert } from "@/types/alerts";
import type { DashboardKpi } from "@/types/dashboard";

const kpi: DashboardKpi = {
  key: "production",
  label: "Production",
  value: 9250,
  unit: "units",
  context_label: "92.5% of target",
  status: "warning",
  status_label: "Below target",
  trend: {
    change_percentage: 4.2,
    direction: "up",
    comparison_label: "vs yesterday",
  },
};

function queryState<T>(overrides: Partial<QueryState<T>>): QueryState<T> {
  return {
    status: "success",
    data: undefined,
    error: undefined,
    isLoading: false,
    isRefreshing: false,
    isSuccess: true,
    isEmpty: false,
    isError: false,
    updatedAt: Date.now(),
    refetch: () => {},
    ...overrides,
  } as QueryState<T>;
}

describe("KPI card", () => {
  it("renders the value, unit and context from the backend", () => {
    render(<KpiCard kpi={kpi} />);

    expect(screen.getByText("9,250")).toBeTruthy();
    expect(screen.getByText("units")).toBeTruthy();
    expect(screen.getByText("92.5% of target")).toBeTruthy();
  });

  it("states the status in words, not only in colour", () => {
    render(<KpiCard kpi={kpi} />);
    // WCAG 1.4.1: the verdict must be readable without perceiving the tint.
    expect(screen.getAllByText("Below target").length).toBeGreaterThan(0);
  });

  it("shows the trend with a sign and the comparison period", () => {
    render(<KpiCard kpi={kpi} />);
    expect(screen.getByText("+4.2%")).toBeTruthy();
    expect(screen.getAllByText(/vs yesterday/).length).toBeGreaterThan(0);
  });

  it("says a comparison is unavailable rather than showing 0%", () => {
    // A null change means there was no previous period. "0.0% vs yesterday"
    // would state something false.
    render(
      <KpiCard
        kpi={{
          ...kpi,
          trend: {
            change_percentage: null,
            direction: "unknown",
            comparison_label: "vs yesterday",
          },
        }}
      />,
    );

    // Twice: once in the visual card, once in the accessible sentence.
    expect(screen.getAllByText(/No vs yesterday comparison/).length).toBe(2);
    expect(screen.queryByText("+0.0%")).toBeNull();
  });

  it("carries a single accessible sentence describing the card", () => {
    const { container } = render(<KpiCard kpi={kpi} />);
    // Read linearly, four separate fragments are hard to follow; the card
    // composes them into one statement for assistive technology.
    const description = container.querySelector(".sr-only");
    expect(description?.textContent).toContain("Production: 9,250 units");
    expect(description?.textContent).toContain("Status: Below target");
    expect(description?.textContent).toContain("up 4.2% vs yesterday");
  });

  it("does not append a unit to a percentage", () => {
    render(<KpiCard kpi={{ ...kpi, value: 74.2, unit: "%" }} />);
    expect(screen.getByText("74.2%")).toBeTruthy();
  });
});

describe("query boundary states", () => {
  it("renders the skeleton and announces loading", () => {
    render(
      <QueryBoundary
        query={queryState({ status: "loading", isLoading: true, isSuccess: false })}
        loadingLabel="Loading production trend"
        skeleton={<div data-testid="skeleton" />}
      >
        {() => <div data-testid="content" />}
      </QueryBoundary>,
    );

    expect(screen.getByTestId("skeleton")).toBeTruthy();
    expect(screen.getByRole("status").textContent).toContain("Loading production trend");
    expect(screen.queryByTestId("content")).toBeNull();
  });

  it("renders an error with a retry when retrying could help", () => {
    render(
      <QueryBoundary
        query={queryState({
          status: "error",
          isError: true,
          isSuccess: false,
          error: new ApiError({ kind: "server", status: 500, message: "boom" }),
        })}
        loadingLabel="Loading"
        skeleton={<div />}
        errorTitle="Unable to refresh production data."
      >
        {() => <div data-testid="content" />}
      </QueryBoundary>,
    );

    expect(screen.getByRole("alert").textContent).toContain("Unable to refresh production data.");
    expect(screen.getByRole("button", { name: /try again/i })).toBeTruthy();
  });

  it("offers no retry on a 403, where retrying cannot succeed", () => {
    render(
      <QueryBoundary
        query={queryState({
          status: "error",
          isError: true,
          isSuccess: false,
          error: new ApiError({ kind: "forbidden", status: 403, message: "Denied" }),
        })}
        loadingLabel="Loading"
        skeleton={<div />}
      >
        {() => <div />}
      </QueryBoundary>,
    );

    expect(screen.getByRole("alert").textContent).toContain("You do not have access");
    expect(screen.queryByRole("button", { name: /try again/i })).toBeNull();
  });

  it("shows no stack trace or status code to the user", () => {
    render(
      <QueryBoundary
        query={queryState({
          status: "error",
          isError: true,
          isSuccess: false,
          error: new ApiError({ kind: "server", status: 500, message: "boom" }),
        })}
        loadingLabel="Loading"
        skeleton={<div />}
      >
        {() => <div />}
      </QueryBoundary>,
    );

    const text = screen.getByRole("alert").textContent ?? "";
    expect(text).not.toContain("500");
    expect(text).not.toContain("Error:");
    expect(text).not.toContain("at ");
  });

  it("renders a meaningful empty state, not a blank card", () => {
    render(
      <QueryBoundary
        query={queryState({ status: "empty", isEmpty: true, isSuccess: false, data: [] })}
        loadingLabel="Loading"
        skeleton={<div />}
        emptyTitle="No production records found"
        emptyMessage="No records match the selected date range."
      >
        {() => <div data-testid="content" />}
      </QueryBoundary>,
    );

    expect(screen.getByText("No production records found")).toBeTruthy();
    expect(screen.getByText(/No records match the selected date range/)).toBeTruthy();
    expect(screen.queryByTestId("content")).toBeNull();
  });

  it("keeps content mounted while refreshing", () => {
    render(
      <QueryBoundary
        query={queryState({ status: "refreshing", isRefreshing: true, data: { total: 1 } })}
        loadingLabel="Loading"
        skeleton={<div data-testid="skeleton" />}
      >
        {() => <div data-testid="content" />}
      </QueryBoundary>,
    );

    // Spec section 16: a background refresh must not blank the dashboard.
    expect(screen.getByTestId("content")).toBeTruthy();
    expect(screen.queryByTestId("skeleton")).toBeNull();
  });
});

describe("OEE breakdown", () => {
  it("shows the composite and all three factors", () => {
    render(<OeeBreakdown oee={74} availability={85} performance={90} quality={96.7} />);

    expect(screen.getByText("74.0%")).toBeTruthy();
    expect(screen.getByText("Availability")).toBeTruthy();
    expect(screen.getByText("Performance")).toBeTruthy();
    expect(screen.getByText("Quality")).toBeTruthy();
  });

  it("names the weakest factor so the number is actionable", () => {
    // Spec section 11: OEE must not be a mysterious single number.
    render(<OeeBreakdown oee={74} availability={61} performance={95} quality={96} />);
    expect(screen.getByText(/Availability is the lowest factor at 61.0%/)).toBeTruthy();
  });

  it("warns when uncapped performance exceeds 100", () => {
    // Above 100 means bad reference cycle-time data, not a fast machine.
    render(
      <OeeBreakdown
        oee={74}
        availability={85}
        performance={100}
        quality={96}
        performanceUncapped={118}
      />,
    );
    expect(screen.getByText(/recorded ideal cycle time is shorter than achievable/)).toBeTruthy();
  });
});

describe("target vs actual", () => {
  it("uses the backend's achievement figure", () => {
    render(
      <TargetVsActual
        planned={10000}
        produced={9250}
        target={10000}
        achievementPercentage={92.5}
        efficiencyPercentage={92.5}
      />,
    );

    expect(screen.getByText("9,250")).toBeTruthy();
    expect(screen.getAllByText("92.5%").length).toBeGreaterThan(0);
  });

  it("says achievement is not applicable when the target is suppressed", () => {
    // The backend zeroes the target when filtering by machine or shift, because
    // targets have no such dimension. "0%" would read as total failure.
    render(
      <TargetVsActual
        planned={1000}
        produced={950}
        target={0}
        achievementPercentage={0}
        efficiencyPercentage={95}
      />,
    );

    expect(screen.getByText("Not applicable")).toBeTruthy();
    expect(screen.getByText(/Targets are set per line and date/)).toBeTruthy();
  });
});

describe("status distribution", () => {
  it("labels every segment with a word and a count", () => {
    render(
      <StatusDistribution
        total={12}
        itemNoun="machines"
        segments={[
          { label: "Running", count: 8, tone: "good" },
          { label: "Idle", count: 2, tone: "neutral" },
          { label: "Maintenance", count: 1, tone: "warn" },
          { label: "Offline", count: 1, tone: "critical" },
        ]}
      />,
    );

    expect(screen.getByText("Running")).toBeTruthy();
    expect(screen.getByText("8")).toBeTruthy();
    // The bar itself carries a text alternative, so the distribution is not
    // conveyed by adjacent colours alone.
    const bar = screen.getByRole("img");
    expect(bar.getAttribute("aria-label")).toContain("8 Running");
    expect(bar.getAttribute("aria-label")).toContain("1 Offline");
  });
});

describe("alerts", () => {
  const alert: Alert = {
    id: "a1",
    alert_type: "LOW_INVENTORY",
    alert_type_label: "Low inventory",
    severity: "CRITICAL",
    severity_label: "Critical",
    status: "OPEN",
    status_label: "Open",
    title: "Aluminium stock below minimum level",
    description: "Stock has fallen under the reorder point for aluminium billet.",
    machine_id: null,
    machine_code: null,
    machine_name: null,
    component_id: null,
    component_name: null,
    inventory_item_id: "i1",
    inventory_item_name: "Aluminium billet",
    line_id: null,
    line_name: null,
    triggered_at: "2026-01-15T06:00:00Z",
    acknowledged_at: null,
    resolved_at: null,
    age_minutes: 120,
  };

  it("renders severity as a word alongside the title", () => {
    render(
      <ul>
        <AlertRow alert={alert} />
      </ul>,
    );

    expect(screen.getByText("Critical")).toBeTruthy();
    expect(screen.getByText("Aluminium stock below minimum level")).toBeTruthy();
    expect(screen.getByText(/Stock has fallen under the reorder point/)).toBeTruthy();
  });

  it("renders a script payload in a description as inert text", () => {
    const hostile: Alert = {
      ...alert,
      description: "<script>alert('XSS')</script> and <img src=x onerror=alert(1)>",
    };
    const { container } = render(
      <ul>
        <AlertRow alert={hostile} />
      </ul>,
    );

    // React's escaping is the mechanism; this asserts it holds for the field
    // most likely to carry stored content (spec section 36).
    expect(container.querySelector("script")).toBeNull();
    expect(container.querySelector("img")).toBeNull();
    expect(screen.getByText(/<script>alert\('XSS'\)<\/script>/)).toBeTruthy();
  });

  it("links to the machine when the alert is about one", () => {
    render(
      <ul>
        <AlertRow
          alert={{ ...alert, machine_id: "m1", machine_code: "CNC-07", machine_name: "Lathe" }}
        />
      </ul>,
    );

    const link = screen.getByRole("link");
    expect(link.getAttribute("href")).toBe("/machines/m1");
    expect(within(link).getByText(/CNC-07/)).toBeTruthy();
  });
});
