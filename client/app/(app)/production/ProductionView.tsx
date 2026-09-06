"use client";

/**
 * `/production` (spec section 20).
 *
 * KPIs, trend, target-vs-actual and a server-paginated record table, all driven
 * by one filter set held in the URL.
 *
 * The filter state is the page's spine. It is read once and passed to every
 * hook, so the summary, the trend, the comparison and the table always describe
 * the same slice of data -- and the URL is shareable, reloadable and
 * back-button-correct (spec section 28).
 */
import { useMemo } from "react";

import { LineTrendChart } from "@/components/charts/Charts";
import { QueryBoundary, RefreshingIndicator } from "@/components/data/QueryBoundary";
import { TargetVsActual } from "@/components/dashboard/Gauges";
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
  useProductionRecords,
  useProductionSummary,
  useProductionTrend,
} from "@/hooks/queries/useProduction";
import {
  useComponentOptions,
  useLineOptions,
  useMachineOptions,
  useShiftOptions,
} from "@/hooks/useFilterOptions";
import { useServerTable, useServerTableState } from "@/hooks/useServerTable";
import { defaultDateRange, useUrlFilters } from "@/hooks/useUrlFilters";
import { toProductionTrendChart } from "@/lib/chart/adapters";
import { productionColumns } from "@/lib/table/columns";
import { formatNumber, formatPercentage } from "@/lib/utils/format";

const FILTER_KEYS = [
  "start_date",
  "end_date",
  "machine_id",
  "component_id",
  "shift_id",
  "line_id",
] as const;

export function ProductionView() {
  const { filters, setFilter, setFilters, reset, activeCount } = useUrlFilters(FILTER_KEYS);

  // Computed once per mount. Recomputing per render would produce a new object
  // identity on every pass and re-key every query beneath it.
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
      shift_id: filters.shift_id,
      line_id: filters.line_id,
    }),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [
      range.start_date,
      range.end_date,
      filters.machine_id,
      filters.component_id,
      filters.shift_id,
      filters.line_id,
    ],
  );

  const summary = useProductionSummary(queryFilters);
  const trend = useProductionTrend(queryFilters);

  const machineOptions = useMachineOptions();
  const componentOptions = useComponentOptions(range);
  const shiftOptions = useShiftOptions(range);
  const lineOptions = useLineOptions(range);

  const tableState = useServerTableState({
    initialSorting: [{ id: "date", desc: true }],
  });
  const records = useProductionRecords({ ...queryFilters, ...tableState.queryFilters });
  const columns = useMemo(() => productionColumns(), []);
  const table = useServerTable({ columns, state: tableState, page: records.data });

  const trendChart = useMemo(() => toProductionTrendChart(trend.data ?? []), [trend.data]);

  return (
    <>
      <PageHeader
        title="Production"
        description="Output against plan and target, by machine, component, shift and line."
        crumbs={[{ label: "Operations", href: "/dashboard" }]}
        meta={<RefreshingIndicator active={summary.isRefreshing || records.isRefreshing} />}
      />

      <FilterBar onReset={reset} activeCount={activeCount}>
        <DateRangeFilter
          startDate={range.start_date}
          endDate={range.end_date}
          onChange={(next) => {
            setFilters(next);
            // A new range can leave the table on a page that no longer exists.
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
          label="Shift"
          value={filters.shift_id}
          options={shiftOptions.options}
          loading={shiftOptions.isLoading}
          allLabel="All shifts"
          onChange={(value) => {
            setFilter("shift_id", value);
            tableState.resetPage();
          }}
        />
        <SelectFilter
          label="Line"
          value={filters.line_id}
          options={lineOptions.options}
          loading={lineOptions.isLoading}
          allLabel="All lines"
          onChange={(value) => {
            setFilter("line_id", value);
            tableState.resetPage();
          }}
        />
      </FilterBar>

      {/* KPIs */}
      <section aria-labelledby="production-kpis" className="mb-4">
        <h2 id="production-kpis" className="sr-only">
          Production summary
        </h2>
        <QueryBoundary
          query={summary}
          loadingLabel="Loading production summary"
          skeleton={
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-4">
              {Array.from({ length: 4 }).map((_, index) => (
                <KpiCardSkeleton key={index} />
              ))}
            </div>
          }
          errorTitle="Unable to load the production summary."
          emptyTitle="No production in this range"
          emptyMessage="Try widening the date range or clearing a filter."
        >
          {(data) => (
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-4">
              <StatCard
                label="Produced"
                value={formatNumber(data.total_produced)}
                unit="units"
                context={`${formatNumber(data.record_count)} records`}
              />
              <StatCard
                label="Accepted"
                value={formatNumber(data.total_accepted)}
                unit="units"
                context={`${formatNumber(data.total_rejected)} rejected`}
              />
              <StatCard
                label="Efficiency vs plan"
                value={formatPercentage(data.efficiency_percentage)}
                context={`${formatNumber(data.total_planned)} units planned`}
              />
              <StatCard
                label="Achievement vs target"
                value={
                  data.target_quantity === 0
                    ? "Not applicable"
                    : formatPercentage(data.achievement_percentage)
                }
                context={
                  data.target_quantity === 0
                    ? "Targets are not set per machine or shift"
                    : `${formatNumber(data.target_quantity)} units targeted`
                }
              />
            </div>
          )}
        </QueryBoundary>
      </section>

      {/* Trend + comparison */}
      <div className="mb-4 grid grid-cols-1 gap-4 xl:grid-cols-3">
        <Section
          title="Production trend"
          description="Produced, target and plan over the selected range"
          className="xl:col-span-2"
        >
          <QueryBoundary
            query={trend}
            loadingLabel="Loading production trend"
            skeleton={<ChartSkeleton />}
            errorTitle="Unable to load the production trend."
            emptyTitle="No production in this range"
            emptyMessage="Nothing was recorded for the selected filters."
          >
            {() => <LineTrendChart data={trendChart} unitLabel="units" />}
          </QueryBoundary>
        </Section>

        <Section title="Target vs actual" description="Totals for the selected range">
          <QueryBoundary
            query={summary}
            loadingLabel="Loading production comparison"
            skeleton={
              <div className="space-y-4">
                <Skeleton className="h-2 w-full" />
                <Skeleton className="h-2 w-full" />
                <Skeleton className="h-2 w-full" />
              </div>
            }
          >
            {(data) =>
              data.has_data ? (
                <TargetVsActual
                  planned={data.total_planned}
                  produced={data.total_produced}
                  target={data.target_quantity}
                  achievementPercentage={data.achievement_percentage}
                  efficiencyPercentage={data.efficiency_percentage}
                />
              ) : (
                <EmptyState title="No production in this range" compact />
              )
            }
          </QueryBoundary>
        </Section>
      </div>

      {/* Records */}
      <Section
        title="Production records"
        description="One row per machine, component and shift"
        flush
        actions={<RefreshingIndicator active={records.isRefreshing} />}
      >
        <QueryBoundary
          query={records}
          loadingLabel="Loading production records"
          skeleton={<TableSkeleton columns={7} />}
          errorTitle="Unable to load production records."
          renderEmptyAsContent
        >
          {(page) => (
            <>
              <DataTable
                table={table.table}
                caption="Production records for the selected filters"
                empty={
                  <EmptyState
                    title="No production records found"
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

/** Kept for the page shell to render a card while Suspense resolves. */
export function ProductionFallback() {
  return (
    <Card className="p-6">
      <Skeleton className="h-4 w-40" />
      <Skeleton className="mt-4 h-32 w-full" />
    </Card>
  );
}
