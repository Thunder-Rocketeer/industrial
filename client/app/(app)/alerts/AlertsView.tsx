"use client";

/**
 * `/alerts` (spec section 25).
 *
 * The alert summary, severity and status filters, and a paginated list.
 *
 * Rendered as a list rather than a table: an alert is a short piece of prose
 * with a subject and a timestamp, not a row of fields, and squeezing the
 * description into a table cell either truncates it or makes the row unreadable.
 * Pagination is still server-driven, so the DOM holds one page at a time.
 */
import { useMemo } from "react";

import { QueryBoundary, RefreshingIndicator } from "@/components/data/QueryBoundary";
import { AlertRow } from "@/components/dashboard/AlertsPanel";
import { StatCard } from "@/components/dashboard/KpiCard";
import { FilterBar, SelectFilter } from "@/components/filters/Filters";
import { PageHeader } from "@/components/layout/PageHeader";
import { TablePagination } from "@/components/tables/DataTable";
import { Card, Section } from "@/components/ui/Card";
import { EmptyState, KpiCardSkeleton, ListSkeleton, Skeleton } from "@/components/ui/States";
import { useAlertSummary, useAlerts } from "@/hooks/queries/useAlerts";
import { useMachineOptions } from "@/hooks/useFilterOptions";
import { useServerTableState } from "@/hooks/useServerTable";
import { useUrlFilters } from "@/hooks/useUrlFilters";
import { toPaginationView } from "@/lib/table/server-table";
import { formatNumber } from "@/lib/utils/format";
import type { AlertSeverity, AlertStatus } from "@/types/common";

const FILTER_KEYS = ["severity", "status", "machine_id"] as const;

const SEVERITY_OPTIONS = [
  { value: "CRITICAL", label: "Critical" },
  { value: "WARNING", label: "Warning" },
  { value: "INFO", label: "Info" },
];

const STATUS_OPTIONS = [
  { value: "OPEN", label: "Open" },
  { value: "ACKNOWLEDGED", label: "Acknowledged" },
  { value: "RESOLVED", label: "Resolved" },
];

export function AlertsView() {
  const { filters, setFilter, reset, activeCount } = useUrlFilters(FILTER_KEYS);

  const summary = useAlertSummary();
  const machineOptions = useMachineOptions();

  // The list is not a TanStack table, but the page/sort state and the
  // 0-based/1-based conversion are the same problem, so the same controller
  // solves it rather than a second hand-rolled one.
  const tableState = useServerTableState();
  const alerts = useAlerts({
    severity: filters.severity as AlertSeverity | undefined,
    status: filters.status as AlertStatus | undefined,
    machine_id: filters.machine_id,
    ...tableState.queryFilters,
  });

  const pagination = useMemo(() => toPaginationView(alerts.data?.pagination), [alerts.data]);

  return (
    <>
      <PageHeader
        title="Alerts"
        description="Operational alerts across machines, inventory and production."
        crumbs={[{ label: "Operations", href: "/dashboard" }]}
        meta={<RefreshingIndicator active={alerts.isRefreshing} />}
      />

      <section aria-labelledby="alert-kpis" className="mb-4">
        <h2 id="alert-kpis" className="sr-only">
          Alert summary
        </h2>
        <QueryBoundary
          query={summary}
          loadingLabel="Loading alert summary"
          skeleton={
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-4">
              {Array.from({ length: 4 }).map((_, index) => (
                <KpiCardSkeleton key={index} />
              ))}
            </div>
          }
          errorTitle="Unable to load the alert summary."
        >
          {(data) => (
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-4">
              <StatCard
                label="Open alerts"
                value={formatNumber(data.total_open)}
                context={`${formatNumber(data.acknowledged_count)} acknowledged`}
                tone={data.total_open === 0 ? "good" : "warn"}
                statusLabel={data.total_open === 0 ? "All clear" : "Attention"}
              />
              <StatCard
                label="Critical"
                value={formatNumber(data.critical_count)}
                context="Needs immediate action"
                tone={data.critical_count > 0 ? "critical" : "good"}
                statusLabel={data.critical_count > 0 ? "Critical" : "Clear"}
              />
              <StatCard label="Warning" value={formatNumber(data.warning_count)} />
              <StatCard label="Info" value={formatNumber(data.info_count)} />
            </div>
          )}
        </QueryBoundary>
      </section>

      <FilterBar onReset={reset} activeCount={activeCount}>
        <SelectFilter
          label="Severity"
          value={filters.severity}
          options={SEVERITY_OPTIONS}
          allLabel="All severities"
          onChange={(value) => {
            setFilter("severity", value);
            tableState.resetPage();
          }}
        />
        <SelectFilter
          label="Status"
          value={filters.status}
          options={STATUS_OPTIONS}
          allLabel="All statuses"
          onChange={(value) => {
            setFilter("status", value);
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
      </FilterBar>

      <Section
        title="Alert history"
        description="Most severe and most recent first"
        flush
        actions={<RefreshingIndicator active={alerts.isRefreshing} />}
      >
        <QueryBoundary
          query={alerts}
          loadingLabel="Loading alerts"
          skeleton={
            <div className="p-4">
              <ListSkeleton rows={6} />
            </div>
          }
          errorTitle="Unable to load alerts."
          renderEmptyAsContent
        >
          {(page) =>
            page.data.length === 0 ? (
              <EmptyState
                title="No alerts found"
                message="No alerts match the selected severity, status or machine."
                icon="mdi:check-circle-outline"
              />
            ) : (
              <>
                <ul className="px-4 py-1">
                  {page.data.map((alert) => (
                    <AlertRow key={alert.id} alert={alert} />
                  ))}
                </ul>
                <TablePagination
                  pagination={pagination}
                  pageSize={page.pagination.page_size}
                  onPrevious={tableState.previousPage}
                  onNext={tableState.nextPage}
                  onPageSizeChange={tableState.setPageSize}
                  disabled={alerts.isRefreshing}
                />
              </>
            )
          }
        </QueryBoundary>
      </Section>
    </>
  );
}

export function AlertsFallback() {
  return (
    <Card className="p-6">
      <Skeleton className="h-4 w-40" />
      <Skeleton className="mt-4 h-32 w-full" />
    </Card>
  );
}
