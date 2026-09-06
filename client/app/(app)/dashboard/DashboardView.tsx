"use client";

/**
 * The executive dashboard (spec sections 3–12).
 *
 * The whole screen answers one question: *is the factory all right?* -- and it
 * has to answer within five to ten seconds of the page opening. The ordering
 * follows the hierarchy in the Phase 6 brief and is not arbitrary:
 *
 *   1. Alerts -- the only thing here that asks the reader to act.
 *   2. KPI cards -- the eight numbers that define "all right".
 *   3. Production and quality -- what the factory made, and how good it was.
 *   4. Machines and inventory -- the two things that stop production.
 *   5. OEE -- the composite, last, because it is a summary of everything above.
 *
 * Two structural decisions:
 *
 * **One request for the whole screen.** `/dashboard/summary` returns production,
 * quality, inventory, machines, OEE, KPIs and alerts in a single response, and
 * the backend computes its nine aggregates concurrently. Eight separate hooks
 * would mean eight round trips, eight loading states and a screen that assembles
 * itself in pieces. The trend series is a second request because it covers 30
 * days and does not need the 30-second refresh.
 *
 * **Nothing here calculates.** Every percentage, status and trend was computed
 * by `services/kpi.py`. The components format.
 */
import { useMemo } from "react";

import { AlertList } from "@/components/dashboard/AlertsPanel";
import { OeeBreakdown, StatusDistribution, TargetVsActual } from "@/components/dashboard/Gauges";
import { KpiCard } from "@/components/dashboard/KpiCard";
import { LastUpdated } from "@/components/dashboard/LastUpdated";
import { QueryBoundary, RefreshingIndicator } from "@/components/data/QueryBoundary";
import { LineTrendChart, ParetoChart } from "@/components/charts/Charts";
import { PageHeader } from "@/components/layout/PageHeader";
import { ButtonLink } from "@/components/ui/Button";
import { Card, Section, Stat } from "@/components/ui/Card";
import { StatusBadge, inventoryStatusTone, machineStatusTone } from "@/components/ui/Status";
import {
  ChartSkeleton,
  EmptyState,
  KpiCardSkeleton,
  ListSkeleton,
  LoadingRegion,
  Skeleton,
} from "@/components/ui/States";
import { useDashboardSummary, useDashboardTrends } from "@/hooks/queries/useDashboard";
import { toDefectParetoChart, toProductionTrendChart } from "@/lib/chart/adapters";
import { formatDate, formatNumber, formatPercentage } from "@/lib/utils/format";
import type { DashboardSummary } from "@/types/dashboard";

export function DashboardView() {
  const summary = useDashboardSummary();
  const trends = useDashboardTrends();

  /*
   * Adapter output is memoized on the response, not rebuilt per render.
   *
   * A new array identity on every render forces Recharts to redraw the whole
   * series. These recompute only when the data actually changes.
   */
  const productionChart = useMemo(
    () => toProductionTrendChart(trends.data?.production ?? []),
    [trends.data],
  );
  const defectChart = useMemo(
    () => toDefectParetoChart(trends.data?.top_defects ?? []),
    [trends.data],
  );

  return (
    <>
      <PageHeader
        title="Factory Operations"
        description="Production, quality, inventory and machine status across all lines."
        meta={
          <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
            <LastUpdated
              at={summary.updatedAt}
              isRefreshing={summary.isRefreshing}
              onRefresh={summary.refetch}
            />
            {summary.data && (
              <span className="text-subtle text-xs">
                Business date{" "}
                <span className="text-muted font-medium">
                  {formatDate(summary.data.business_date)}
                </span>
              </span>
            )}
          </div>
        }
      />

      {/* ---------------------------------------------------------------
          1. Alerts — first in the DOM as well as on screen, so a screen
             reader meets them first too.
          --------------------------------------------------------------- */}
      <div className="mb-4">
        <QueryBoundary
          query={summary}
          loadingLabel="Loading alerts"
          skeleton={
            <Card className="p-4">
              <ListSkeleton rows={2} />
            </Card>
          }
        >
          {(data) => <CriticalAlertsBanner summary={data} />}
        </QueryBoundary>
      </div>

      {/* ---------------------------------------------------------------
          2. KPI cards
          --------------------------------------------------------------- */}
      <section aria-labelledby="kpi-heading" className="mb-4">
        <h2 id="kpi-heading" className="sr-only">
          Key performance indicators
        </h2>
        <QueryBoundary
          query={summary}
          loadingLabel="Loading key performance indicators"
          skeleton={
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-4">
              {Array.from({ length: 8 }).map((_, index) => (
                <KpiCardSkeleton key={index} />
              ))}
            </div>
          }
        >
          {(data) =>
            data.kpis.length === 0 ? (
              <Card>
                <EmptyState
                  title="No KPIs available"
                  message="The backend returned no indicators for the current business date."
                  compact
                />
              </Card>
            ) : (
              <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-4">
                {data.kpis.map((kpi) => (
                  <KpiCard key={kpi.key} kpi={kpi} />
                ))}
              </div>
            )
          }
        </QueryBoundary>
      </section>

      {/* ---------------------------------------------------------------
          3. Production trend + alerts list
          `xl:grid-cols-3` with the chart spanning two: the trend needs the
          width to be readable, the alert list does not.
          --------------------------------------------------------------- */}
      <div className="mb-4 grid grid-cols-1 gap-4 xl:grid-cols-3">
        <Section
          title="Production trend"
          description="Produced against target and plan, last 30 days"
          className="xl:col-span-2"
          actions={
            <>
              <RefreshingIndicator active={trends.isRefreshing} />
              <ButtonLink href="/production" size="sm" variant="ghost">
                View production
              </ButtonLink>
            </>
          }
        >
          <QueryBoundary
            query={trends}
            loadingLabel="Loading production trend"
            skeleton={<ChartSkeleton />}
            errorTitle="Unable to load production trend."
            emptyTitle="No production in this period"
            emptyMessage="Nothing was recorded in the last 30 days."
          >
            {() => <LineTrendChart data={productionChart} unitLabel="units" />}
          </QueryBoundary>
        </Section>

        <Section
          title="Active alerts"
          description="Highest severity first"
          actions={
            <ButtonLink href="/alerts" size="sm" variant="ghost">
              View all
            </ButtonLink>
          }
        >
          <QueryBoundary
            query={summary}
            loadingLabel="Loading alerts"
            skeleton={<ListSkeleton rows={4} />}
            errorTitle="Unable to load alerts."
          >
            {(data) =>
              data.recent_alerts.length === 0 ? (
                <EmptyState
                  title="No open alerts"
                  message="Nothing needs attention right now."
                  icon="mdi:check-circle-outline"
                  compact
                />
              ) : (
                <AlertList alerts={data.recent_alerts.slice(0, 6)} />
              )
            }
          </QueryBoundary>
        </Section>
      </div>

      {/* ---------------------------------------------------------------
          4. Target vs actual + quality
          --------------------------------------------------------------- */}
      <div className="mb-4 grid grid-cols-1 gap-4 lg:grid-cols-2">
        <Section
          title="Target vs actual"
          description="Today's output against plan and target"
          actions={<RefreshingIndicator active={summary.isRefreshing} />}
        >
          <QueryBoundary
            query={summary}
            loadingLabel="Loading production comparison"
            skeleton={
              <div className="space-y-4">
                <Skeleton className="h-2 w-full" />
                <Skeleton className="h-2 w-full" />
                <Skeleton className="h-2 w-full" />
                <Skeleton className="h-12 w-full" />
              </div>
            }
          >
            {(data) =>
              data.production.has_data ? (
                <TargetVsActual
                  planned={data.production.total_planned}
                  produced={data.production.total_produced}
                  target={data.production.target_quantity}
                  achievementPercentage={data.production.achievement_percentage}
                  efficiencyPercentage={data.production.efficiency_percentage}
                />
              ) : (
                <EmptyState
                  title="No production recorded"
                  message="Nothing has been produced on the current business date."
                  compact
                />
              )
            }
          </QueryBoundary>
        </Section>

        <Section
          title="Quality"
          description="Inspection results for the current period"
          actions={
            <ButtonLink href="/quality" size="sm" variant="ghost">
              View quality
            </ButtonLink>
          }
        >
          <QueryBoundary
            query={summary}
            loadingLabel="Loading quality summary"
            skeleton={
              <div className="grid grid-cols-2 gap-4">
                {Array.from({ length: 4 }).map((_, index) => (
                  <div key={index}>
                    <Skeleton className="h-3 w-16" />
                    <Skeleton className="mt-2 h-6 w-20" />
                  </div>
                ))}
              </div>
            }
          >
            {(data) =>
              data.quality.has_data ? (
                <dl className="grid grid-cols-2 gap-4 sm:grid-cols-3">
                  <Stat label="Inspected" value={formatNumber(data.quality.total_inspected)} />
                  <Stat label="Accepted" value={formatNumber(data.quality.total_passed)} />
                  <Stat label="Rejected" value={formatNumber(data.quality.total_rejected)} />
                  <Stat
                    label="Defect rate"
                    value={formatPercentage(data.quality.defect_rate_percentage, 2)}
                  />
                  <Stat
                    label="First-pass yield"
                    value={formatPercentage(data.quality.first_pass_yield_percentage)}
                  />
                  <Stat
                    label="Defect types"
                    value={formatNumber(data.quality.distinct_defect_types)}
                  />
                </dl>
              ) : (
                <EmptyState
                  title="No inspections recorded"
                  message="No quality records exist for the current period."
                  compact
                />
              )
            }
          </QueryBoundary>
        </Section>
      </div>

      {/* ---------------------------------------------------------------
          5. Defect Pareto
          --------------------------------------------------------------- */}
      <div className="mb-4">
        <Section
          title="Top defect causes"
          description="Rejected units by defect type, with cumulative share"
        >
          <QueryBoundary
            query={trends}
            loadingLabel="Loading defect analysis"
            skeleton={<ChartSkeleton height={280} />}
            errorTitle="Unable to load defect analysis."
            emptyTitle="No defects recorded"
            emptyMessage="No rejections in the last 30 days."
          >
            {() => <ParetoChart data={defectChart} />}
          </QueryBoundary>
        </Section>
      </div>

      {/* ---------------------------------------------------------------
          6. Machines + inventory — the two things that stop production
          --------------------------------------------------------------- */}
      <div className="mb-4 grid grid-cols-1 gap-4 lg:grid-cols-2">
        <Section
          title="Machine status"
          description="Fleet availability right now"
          actions={
            <ButtonLink href="/machines" size="sm" variant="ghost">
              View machines
            </ButtonLink>
          }
        >
          <QueryBoundary
            query={summary}
            loadingLabel="Loading machine status"
            skeleton={
              <div className="space-y-4">
                <Skeleton className="h-2.5 w-full" />
                <div className="grid grid-cols-4 gap-4">
                  {Array.from({ length: 4 }).map((_, index) => (
                    <Skeleton key={index} className="h-10" />
                  ))}
                </div>
              </div>
            }
          >
            {(data) => <MachineStatusPanel summary={data} />}
          </QueryBoundary>
        </Section>

        <Section
          title="Inventory health"
          description="Stock position across all materials"
          actions={
            <ButtonLink href="/inventory" size="sm" variant="ghost">
              View inventory
            </ButtonLink>
          }
        >
          <QueryBoundary
            query={summary}
            loadingLabel="Loading inventory health"
            skeleton={
              <div className="space-y-4">
                <Skeleton className="h-2.5 w-full" />
                <div className="grid grid-cols-4 gap-4">
                  {Array.from({ length: 4 }).map((_, index) => (
                    <Skeleton key={index} className="h-10" />
                  ))}
                </div>
              </div>
            }
          >
            {(data) => <InventoryHealthPanel summary={data} />}
          </QueryBoundary>
        </Section>
      </div>

      {/* ---------------------------------------------------------------
          7. OEE — the composite, last
          --------------------------------------------------------------- */}
      <Section
        title="Overall equipment effectiveness"
        description="Availability × performance × quality, calculated by the backend"
        actions={
          <ButtonLink href="/analytics" size="sm" variant="ghost">
            View analytics
          </ButtonLink>
        }
      >
        <QueryBoundary
          query={summary}
          loadingLabel="Loading OEE"
          skeleton={
            <LoadingRegion label="Loading OEE">
              <div className="flex flex-col gap-4 sm:flex-row">
                <Skeleton className="h-20 w-40" />
                <div className="flex-1 space-y-3">
                  <Skeleton className="h-2 w-full" />
                  <Skeleton className="h-2 w-full" />
                  <Skeleton className="h-2 w-full" />
                </div>
              </div>
            </LoadingRegion>
          }
        >
          {(data) => (
            <OeeBreakdown
              oee={data.oee.oee_percentage}
              availability={data.oee.availability_percentage}
              performance={data.oee.performance_percentage}
              quality={data.oee.quality_percentage}
              performanceUncapped={data.oee.performance_uncapped_percentage}
            />
          )}
        </QueryBoundary>
      </Section>
    </>
  );
}

/* ------------------------------------------------------------------------- */

/**
 * A prominent banner when something is critical.
 *
 * Deliberately not shown when nothing is wrong: a permanent "0 critical alerts"
 * strip trains people to ignore the space where the real warning will appear.
 */
function CriticalAlertsBanner({ summary }: { summary: DashboardSummary }) {
  const { alerts } = summary;

  if (alerts.total_open === 0) {
    return (
      <Card className="flex items-center gap-2.5 px-4 py-2.5">
        <StatusBadge tone="good" withIcon size="sm">
          All clear
        </StatusBadge>
        <p className="text-muted text-sm">No open alerts across the factory.</p>
      </Card>
    );
  }

  const tone = alerts.critical_count > 0 ? "critical" : "warn";

  return (
    <Card
      className={`flex flex-wrap items-center gap-x-3 gap-y-2 px-4 py-3 ${
        alerts.critical_count > 0 ? "border-critical/40" : "border-warn/40"
      }`}
    >
      <StatusBadge tone={tone} withIcon size="sm">
        {alerts.critical_count > 0 ? "Critical" : "Attention needed"}
      </StatusBadge>
      <p className="text-foreground min-w-0 flex-1 text-sm">
        <span className="font-semibold">{formatNumber(alerts.total_open)}</span> open{" "}
        {alerts.total_open === 1 ? "alert" : "alerts"}
        {alerts.critical_count > 0 && (
          <>
            {" "}
            — <span className="font-semibold">{formatNumber(alerts.critical_count)}</span> critical
          </>
        )}
        {alerts.warning_count > 0 && <>, {formatNumber(alerts.warning_count)} warning</>}
      </p>
      <ButtonLink href="/alerts" size="sm" variant={tone === "critical" ? "danger" : "secondary"}>
        Review alerts
      </ButtonLink>
    </Card>
  );
}

function MachineStatusPanel({ summary }: { summary: DashboardSummary }) {
  const { machines } = summary;

  if (machines.total_machines === 0) {
    return <EmptyState title="No machines configured" compact />;
  }

  return (
    <div className="space-y-4">
      <StatusDistribution
        total={machines.total_machines}
        itemNoun="machines"
        segments={machines.status_breakdown.map((entry) => ({
          label: entry.status_label,
          count: entry.count,
          tone: machineStatusTone(entry.status),
        }))}
      />
      <dl className="border-border-base grid grid-cols-2 gap-4 border-t pt-3">
        <Stat
          label="Availability"
          value={formatPercentage(machines.availability_percentage)}
          hint="Running machines as a share of the fleet"
        />
        <Stat
          label="Maintenance due"
          value={formatNumber(machines.maintenance_due_count)}
          hint="Within the attention window, or overdue"
        />
      </dl>
    </div>
  );
}

function InventoryHealthPanel({ summary }: { summary: DashboardSummary }) {
  const { inventory } = summary;

  if (inventory.total_items === 0) {
    return <EmptyState title="No inventory items" compact />;
  }

  return (
    <div className="space-y-4">
      <StatusDistribution
        total={inventory.total_items}
        itemNoun="items"
        segments={inventory.status_breakdown.map((entry) => ({
          label: entry.status_label,
          count: entry.count,
          tone: inventoryStatusTone(entry.status),
        }))}
      />
      <dl className="border-border-base grid grid-cols-2 gap-4 border-t pt-3">
        <Stat
          label="Needs attention"
          value={formatNumber(inventory.items_requiring_attention)}
          hint="Below reorder point"
        />
        <Stat
          label="Stock health"
          value={formatPercentage(inventory.health_percentage)}
          hint="Share of items in a healthy state"
        />
      </dl>
    </div>
  );
}
