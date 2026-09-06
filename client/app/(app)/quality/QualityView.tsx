"use client";

/**
 * `/quality` (spec sections 7 and 21).
 *
 * Quality KPIs, the defect-rate trend, the Pareto, and the inspection records.
 *
 * The Pareto is the point of this page. The backend returns defect categories
 * already ranked with a cumulative share, so the chart shows -- without anyone
 * doing arithmetic -- that a handful of causes account for most of the
 * rejections. Recomputing those percentages here over a truncated copy of the
 * list would produce a curve that looks plausible and is wrong.
 */
import { useMemo } from "react";

import { LineTrendChart, ParetoChart } from "@/components/charts/Charts";
import { QueryBoundary, RefreshingIndicator } from "@/components/data/QueryBoundary";
import { StatCard } from "@/components/dashboard/KpiCard";
import { DateRangeFilter, FilterBar, SelectFilter } from "@/components/filters/Filters";
import { PageHeader } from "@/components/layout/PageHeader";
import { DataTable, TablePagination } from "@/components/tables/DataTable";
import { Card, Section } from "@/components/ui/Card";
import {
  ChartSkeleton,
  EmptyState,
  KpiCardSkeleton,
  Skeleton,
  TableSkeleton,
} from "@/components/ui/States";
import {
  useDefectBreakdown,
  useDefectTrend,
  useQualityRecords,
  useQualitySummary,
} from "@/hooks/queries/useQuality";
import { useComponentOptions, useDefectOptions, useMachineOptions } from "@/hooks/useFilterOptions";
import { useServerTable, useServerTableState } from "@/hooks/useServerTable";
import { defaultDateRange, useUrlFilters } from "@/hooks/useUrlFilters";
import { toDefectParetoChart, toDefectTrendChart } from "@/lib/chart/adapters";
import { qualityColumns } from "@/lib/table/columns";
import { formatNumber, formatPercentage } from "@/lib/utils/format";

const FILTER_KEYS = [
  "start_date",
  "end_date",
  "machine_id",
  "component_id",
  "defect_id",
  "rejections_only",
] as const;

export function QualityView() {
  const { filters, setFilter, setFilters, reset, activeCount } = useUrlFilters(FILTER_KEYS);
  const fallbackRange = useMemo(() => defaultDateRange(30), []);

  const range = {
    start_date: filters.start_date ?? fallbackRange.start_date,
    end_date: filters.end_date ?? fallbackRange.end_date,
  };

  const queryFilters = useMemo(
    () => ({
      ...range,
      machine_id: filters.machine_id,
      component_id: filters.component_id,
      defect_id: filters.defect_id,
    }),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [range.start_date, range.end_date, filters.machine_id, filters.component_id, filters.defect_id],
  );

  const summary = useQualitySummary(queryFilters);
  const trend = useDefectTrend(queryFilters);
  const breakdown = useDefectBreakdown({ ...queryFilters, limit: 20 });

  const machineOptions = useMachineOptions();
  const componentOptions = useComponentOptions(range);
  const defectOptions = useDefectOptions(range);

  const tableState = useServerTableState({
    initialSorting: [{ id: "inspected_at", desc: true }],
  });
  // Rejection lines carry the defect information; the pass lines do not. The
  // default view of "quality records" is therefore the rejections, which is
  // also what the backend's `rejections_only` flag defaults this page to.
  const rejectionsOnly = filters.rejections_only !== "false";
  const records = useQualityRecords({
    ...queryFilters,
    rejections_only: rejectionsOnly,
    ...tableState.queryFilters,
  });
  const columns = useMemo(() => qualityColumns(), []);
  const table = useServerTable({ columns, state: tableState, page: records.data });

  const trendChart = useMemo(() => toDefectTrendChart(trend.data ?? []), [trend.data]);
  const paretoChart = useMemo(() => toDefectParetoChart(breakdown.data ?? []), [breakdown.data]);

  return (
    <>
      <PageHeader
        title="Quality"
        description="Inspection results, defect rates and the causes behind them."
        crumbs={[{ label: "Operations", href: "/dashboard" }]}
        meta={<RefreshingIndicator active={summary.isRefreshing || records.isRefreshing} />}
      />

      <FilterBar onReset={reset} activeCount={activeCount}>
        <DateRangeFilter
          startDate={range.start_date}
          endDate={range.end_date}
          onChange={(next) => {
            setFilters(next);
            tableState.resetPage();
          }}
        />
        <SelectFilter
          label="Machine"
          value={filters.machine_id}
          options={machineOptions.options}
          loading={machineOptions.isLoading}
          allLabel="All machines"
          onChange={(value) => {
            setFilter("machine_id", value);
            tableState.resetPage();
          }}
        />
        <SelectFilter
          label="Component"
          value={filters.component_id}
          options={componentOptions.options}
          loading={componentOptions.isLoading}
          allLabel="All components"
          onChange={(value) => {
            setFilter("component_id", value);
            tableState.resetPage();
          }}
        />
        <SelectFilter
          label="Defect"
          value={filters.defect_id}
          options={defectOptions.options}
          loading={defectOptions.isLoading}
          allLabel="All defects"
          onChange={(value) => {
            setFilter("defect_id", value);
            tableState.resetPage();
          }}
        />
        <SelectFilter
          label="Records"
          value={filters.rejections_only ?? "true"}
          options={[
            { value: "true", label: "Rejections only" },
            { value: "false", label: "All inspections" },
          ]}
          allLabel="Rejections only"
          onChange={(value) => {
            setFilter("rejections_only", value);
            tableState.resetPage();
          }}
        />
      </FilterBar>

      <section aria-labelledby="quality-kpis" className="mb-4">
        <h2 id="quality-kpis" className="sr-only">
          Quality summary
        </h2>
        <QueryBoundary
          query={summary}
          loadingLabel="Loading quality summary"
          skeleton={
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-4">
              {Array.from({ length: 4 }).map((_, index) => (
                <KpiCardSkeleton key={index} />
              ))}
            </div>
          }
          errorTitle="Unable to load the quality summary."
          emptyTitle="No inspections in this range"
          emptyMessage="Try widening the date range or clearing a filter."
        >
          {(data) => (
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-4">
              <StatCard
                label="Inspected"
                value={formatNumber(data.total_inspected)}
                unit="units"
                context={`${formatNumber(data.record_count)} inspection records`}
              />
              <StatCard
                label="Rejected"
                value={formatNumber(data.total_rejected)}
                unit="units"
                context={`${formatNumber(data.total_rework)} reworked`}
              />
              <StatCard
                label="Defect rate"
                value={formatPercentage(data.defect_rate_percentage, 2)}
                context={`${formatNumber(data.distinct_defect_types)} distinct defect types`}
              />
              <StatCard
                label="First-pass yield"
                value={formatPercentage(data.first_pass_yield_percentage)}
                context={`Quality rate ${formatPercentage(data.quality_rate_percentage)}`}
              />
            </div>
          )}
        </QueryBoundary>
      </section>

      <div className="mb-4 grid grid-cols-1 gap-4 xl:grid-cols-2">
        <Section title="Defect rate trend" description="Rejections as a share of units inspected">
          <QueryBoundary
            query={trend}
            loadingLabel="Loading defect trend"
            skeleton={<ChartSkeleton />}
            errorTitle="Unable to load the defect trend."
            emptyTitle="No inspections in this range"
          >
            {() => <LineTrendChart data={trendChart} unitLabel="%" domain={[0, "auto"]} />}
          </QueryBoundary>
        </Section>

        <Section title="Defect Pareto" description="Largest causes first, with cumulative share">
          <QueryBoundary
            query={breakdown}
            loadingLabel="Loading defect breakdown"
            skeleton={<ChartSkeleton height={280} />}
            errorTitle="Unable to load the defect breakdown."
            emptyTitle="No defects recorded"
            emptyMessage="No rejections match the selected filters."
          >
            {() => <ParetoChart data={paretoChart} />}
          </QueryBoundary>
        </Section>
      </div>

      <Section
        title="Inspection records"
        description={rejectionsOnly ? "Rejection lines only" : "All inspection lines"}
        flush
        actions={<RefreshingIndicator active={records.isRefreshing} />}
      >
        <QueryBoundary
          query={records}
          loadingLabel="Loading inspection records"
          skeleton={<TableSkeleton columns={7} />}
          errorTitle="Unable to load inspection records."
          renderEmptyAsContent
        >
          {(page) => (
            <>
              <DataTable
                table={table.table}
                caption="Quality inspection records for the selected filters"
                empty={
                  <EmptyState
                    title="No inspection records found"
                    message="No records match the selected date range and filters."
                    compact
                  />
                }
              />
              <TablePagination
                pagination={table.pagination}
                pageSize={page.pagination.page_size}
                onPrevious={tableState.previousPage}
                onNext={tableState.nextPage}
                onPageSizeChange={tableState.setPageSize}
                disabled={records.isRefreshing}
              />
            </>
          )}
        </QueryBoundary>
      </Section>
    </>
  );
}

export function QualityFallback() {
  return (
    <Card className="p-6">
      <Skeleton className="h-4 w-40" />
      <Skeleton className="mt-4 h-32 w-full" />
    </Card>
  );
}
