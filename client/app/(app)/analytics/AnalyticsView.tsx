"use client";

/**
 * `/analytics` (spec sections 11 and 24).
 *
 * OEE and its factors, efficiency against plan and target, downtime by machine,
 * and the defect picture.
 *
 * Spec section 24 says not to create redundant charts, and the selection here
 * follows from that: each visualization answers a question the others cannot.
 * The OEE trend shows *when* effectiveness moved; OEE by machine shows *where*;
 * downtime by machine shows *why*, for the availability half of it. The defect
 * Pareto covers the quality half. There is deliberately no second OEE gauge and
 * no repeat of the production trend, both of which live elsewhere.
 *
 * These are the most expensive queries the API serves and they never poll: they
 * describe a period that has already ended.
 */
import { useMemo } from "react";

import { GroupedBarChart, LineTrendChart, ParetoChart } from "@/components/charts/Charts";
import { QueryBoundary } from "@/components/data/QueryBoundary";
import { OeeBreakdown } from "@/components/dashboard/Gauges";
import { StatCard } from "@/components/dashboard/KpiCard";
import { DateRangeFilter, FilterBar, SelectFilter } from "@/components/filters/Filters";
import { PageHeader } from "@/components/layout/PageHeader";
import { Card, Section, Stat } from "@/components/ui/Card";
import { ChartSkeleton, KpiCardSkeleton, Skeleton } from "@/components/ui/States";
import {
  useDefectAnalytics,
  useDowntimeByMachine,
  useEfficiencyTrend,
  useOee,
  useOeeByMachine,
  useOeeTrend,
  useProductionEfficiency,
} from "@/hooks/queries/useAnalytics";
import { useMachineOptions } from "@/hooks/useFilterOptions";
import { defaultDateRange, useUrlFilters } from "@/hooks/useUrlFilters";
import {
  toDefectParetoChart,
  toDowntimeByMachineChart,
  toEfficiencyTrendChart,
  toOeeByMachineChart,
  toOeeTrendChart,
} from "@/lib/chart/adapters";
import { formatMinutes, formatNumber, formatPercentage } from "@/lib/utils/format";

const FILTER_KEYS = ["start_date", "end_date", "machine_id"] as const;

export function AnalyticsView() {
  const { filters, setFilter, setFilters, reset, activeCount } = useUrlFilters(FILTER_KEYS);
  const fallbackRange = useMemo(() => defaultDateRange(30), []);

  const range = {
    start_date: filters.start_date ?? fallbackRange.start_date,
    end_date: filters.end_date ?? fallbackRange.end_date,
  };

  const queryFilters = useMemo(
    () => ({ ...range, machine_id: filters.machine_id }),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [range.start_date, range.end_date, filters.machine_id],
  );

  const oee = useOee(queryFilters);
  const oeeTrend = useOeeTrend(queryFilters);
  const oeeByMachine = useOeeByMachine(queryFilters);
  const efficiency = useProductionEfficiency(queryFilters);
  const efficiencyTrend = useEfficiencyTrend(queryFilters);
  const downtime = useDowntimeByMachine(queryFilters);
  const defects = useDefectAnalytics(queryFilters);

  const machineOptions = useMachineOptions();

  const oeeTrendChart = useMemo(() => toOeeTrendChart(oeeTrend.data ?? []), [oeeTrend.data]);
  const oeeMachineChart = useMemo(
    () => toOeeByMachineChart(oeeByMachine.data ?? []),
    [oeeByMachine.data],
  );
  const efficiencyChart = useMemo(
    () => toEfficiencyTrendChart(efficiencyTrend.data ?? []),
    [efficiencyTrend.data],
  );
  const downtimeChart = useMemo(
    () => toDowntimeByMachineChart(downtime.data ?? []),
    [downtime.data],
  );
  const defectChart = useMemo(
    () => toDefectParetoChart(defects.data?.by_defect ?? []),
    [defects.data],
  );

  return (
    <>
      <PageHeader
        title="Analytics"
        description="Effectiveness, efficiency and defect analysis over a chosen period."
        crumbs={[{ label: "Operations", href: "/dashboard" }]}
      />

      <FilterBar onReset={reset} activeCount={activeCount}>
        <DateRangeFilter
          startDate={range.start_date}
          endDate={range.end_date}
          onChange={setFilters}
        />
        <SelectFilter
          label="Machine"
          value={filters.machine_id}
          options={machineOptions.options}
          loading={machineOptions.isLoading}
          allLabel="All machines"
          onChange={(value) => setFilter("machine_id", value)}
        />
      </FilterBar>

      {/* Headline figures */}
      <section aria-labelledby="analytics-kpis" className="mb-4">
        <h2 id="analytics-kpis" className="sr-only">
          Analytics summary
        </h2>
        <QueryBoundary
          query={oee}
          loadingLabel="Loading OEE summary"
          skeleton={
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-4">
              {Array.from({ length: 4 }).map((_, index) => (
                <KpiCardSkeleton key={index} />
              ))}
            </div>
          }
          errorTitle="Unable to load OEE."
          emptyTitle="No data in this range"
          emptyMessage="Nothing ran during the selected period."
        >
          {(data) => (
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-4">
              <StatCard
                label="OEE"
                value={formatPercentage(data.oee_percentage)}
                context={`${formatNumber(data.record_count)} production records`}
              />
              <StatCard
                label="Availability"
                value={formatPercentage(data.availability_percentage)}
                context={`${formatMinutes(data.downtime_minutes)} downtime`}
              />
              <StatCard
                label="Performance"
                value={formatPercentage(data.performance_percentage)}
                context={`${formatNumber(data.ideal_output)} units ideal output`}
              />
              <StatCard
                label="Quality"
                value={formatPercentage(data.quality_percentage)}
                context={`${formatNumber(data.rejected_quantity)} units rejected`}
              />
            </div>
          )}
        </QueryBoundary>
      </section>

      {/* OEE breakdown + trend */}
      <div className="mb-4 grid grid-cols-1 gap-4 xl:grid-cols-3">
        <Section title="OEE breakdown" description="Which factor is holding OEE back">
          <QueryBoundary
            query={oee}
            loadingLabel="Loading OEE breakdown"
            skeleton={
              <div className="space-y-3">
                <Skeleton className="h-10 w-24" />
                <Skeleton className="h-2 w-full" />
                <Skeleton className="h-2 w-full" />
                <Skeleton className="h-2 w-full" />
              </div>
            }
            emptyTitle="No data in this range"
          >
            {(data) => (
              <OeeBreakdown
                compact
                oee={data.oee_percentage}
                availability={data.availability_percentage}
                performance={data.performance_percentage}
                quality={data.quality_percentage}
                performanceUncapped={data.performance_uncapped_percentage}
              />
            )}
          </QueryBoundary>
        </Section>

        <Section
          title="OEE trend"
          description="Daily effectiveness with its three factors"
          className="xl:col-span-2"
        >
          <QueryBoundary
            query={oeeTrend}
            loadingLabel="Loading OEE trend"
            skeleton={<ChartSkeleton />}
            errorTitle="Unable to load the OEE trend."
            emptyTitle="No OEE data in this range"
          >
            {() => <LineTrendChart data={oeeTrendChart} unitLabel="%" domain={[0, 100]} />}
          </QueryBoundary>
        </Section>
      </div>

      {/* Efficiency */}
      <div className="mb-4 grid grid-cols-1 gap-4 xl:grid-cols-3">
        <Section title="Production efficiency" description="Output against plan and target">
          <QueryBoundary
            query={efficiency}
            loadingLabel="Loading production efficiency"
            skeleton={
              <div className="grid grid-cols-2 gap-4">
                {Array.from({ length: 4 }).map((_, index) => (
                  <Skeleton key={index} className="h-12" />
                ))}
              </div>
            }
            emptyTitle="No production in this range"
          >
            {(data) => (
              <dl className="grid grid-cols-2 gap-4">
                <Stat
                  label="Efficiency vs plan"
                  value={formatPercentage(data.efficiency_percentage)}
                />
                <Stat
                  label="Achievement vs target"
                  value={
                    data.total_target === 0
                      ? "Not applicable"
                      : formatPercentage(data.achievement_percentage)
                  }
                />
                <Stat label="Produced" value={formatNumber(data.total_produced)} hint="units" />
                <Stat
                  label="Downtime"
                  value={formatPercentage(data.downtime_percentage)}
                  hint={`${formatMinutes(data.total_downtime_minutes)} lost`}
                />
              </dl>
            )}
          </QueryBoundary>
        </Section>

        <Section
          title="Efficiency trend"
          description="Against plan and against target, daily"
          className="xl:col-span-2"
        >
          <QueryBoundary
            query={efficiencyTrend}
            loadingLabel="Loading efficiency trend"
            skeleton={<ChartSkeleton />}
            errorTitle="Unable to load the efficiency trend."
            emptyTitle="No production in this range"
          >
            {() => <LineTrendChart data={efficiencyChart} unitLabel="%" domain={[0, "auto"]} />}
          </QueryBoundary>
        </Section>
      </div>

      {/* Fleet comparisons */}
      <div className="mb-4 grid grid-cols-1 gap-4 lg:grid-cols-2">
        <Section title="OEE by machine" description="Lowest first — where to look">
          <QueryBoundary
            query={oeeByMachine}
            loadingLabel="Loading OEE by machine"
            skeleton={<ChartSkeleton height={300} />}
            errorTitle="Unable to load OEE by machine."
            emptyTitle="No machine data in this range"
          >
            {() => <GroupedBarChart data={oeeMachineChart} unitLabel="%" horizontal height={300} />}
          </QueryBoundary>
        </Section>

        <Section title="Downtime by machine" description="Worst first — why availability is low">
          <QueryBoundary
            query={downtime}
            loadingLabel="Loading downtime by machine"
            skeleton={<ChartSkeleton height={300} />}
            errorTitle="Unable to load downtime by machine."
            emptyTitle="No downtime recorded in this range"
          >
            {() => <GroupedBarChart data={downtimeChart} unitLabel="min" horizontal height={300} />}
          </QueryBoundary>
        </Section>
      </div>

      {/* Defects */}
      <Section
        title="Defect analysis"
        description="Rejection causes ranked by volume, with cumulative share"
      >
        <QueryBoundary
          query={defects}
          loadingLabel="Loading defect analysis"
          skeleton={<ChartSkeleton height={300} />}
          errorTitle="Unable to load defect analysis."
          emptyTitle="No defects recorded in this range"
          emptyMessage="No rejections were logged for the selected filters."
        >
          {(data) => (
            <div className="space-y-4">
              <dl className="grid grid-cols-2 gap-4 sm:grid-cols-4">
                <Stat label="Inspected" value={formatNumber(data.total_inspected)} hint="units" />
                <Stat label="Rejected" value={formatNumber(data.total_rejected)} hint="units" />
                <Stat
                  label="Defect rate"
                  value={formatPercentage(data.defect_rate_percentage, 2)}
                />
                <Stat label="Defect types" value={formatNumber(data.by_defect.length)} />
              </dl>
              <ParetoChart data={defectChart} height={300} />
            </div>
          )}
        </QueryBoundary>
      </Section>
    </>
  );
}

export function AnalyticsFallback() {
  return (
    <Card className="p-6">
      <Skeleton className="h-4 w-40" />
      <Skeleton className="mt-4 h-32 w-full" />
    </Card>
  );
}
