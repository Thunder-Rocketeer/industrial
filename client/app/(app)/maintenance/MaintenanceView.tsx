"use client";

/**
 * `/maintenance` (spec section 26).
 *
 * Upcoming work, recent work, and the full record table.
 *
 * Upcoming and recent are two separate queries rather than one list split in
 * the browser. The backend orders them differently -- soonest first for
 * upcoming, most recent first for history -- and `upcoming_only` is part of the
 * query key, so they are two cache entries rather than two views of one.
 */
import { useMemo } from "react";

import { QueryBoundary, RefreshingIndicator } from "@/components/data/QueryBoundary";
import { StatCard } from "@/components/dashboard/KpiCard";
import { FilterBar, SelectFilter } from "@/components/filters/Filters";
import { PageHeader } from "@/components/layout/PageHeader";
import { DataTable, TablePagination } from "@/components/tables/DataTable";
import { Card, Section } from "@/components/ui/Card";
import { Icon } from "@/components/ui/Icon";
import { StatusBadge, maintenanceStatusTone } from "@/components/ui/Status";
import {
  EmptyState,
  KpiCardSkeleton,
  ListSkeleton,
  Skeleton,
  TableSkeleton,
} from "@/components/ui/States";
import { useMachineSummary } from "@/hooks/queries/useMachines";
import { useMaintenanceRecords, useUpcomingMaintenance } from "@/hooks/queries/useMaintenance";
import { useMachineOptions } from "@/hooks/useFilterOptions";
import { useServerTable, useServerTableState } from "@/hooks/useServerTable";
import { useUrlFilters } from "@/hooks/useUrlFilters";
import { maintenanceColumns } from "@/lib/table/columns";
import { formatDate, formatMinutes, formatNumber, formatText } from "@/lib/utils/format";
import type { MaintenanceStatus } from "@/types/common";
import type { MaintenanceRecord } from "@/types/machines";

const FILTER_KEYS = ["status", "machine_id"] as const;

const STATUS_OPTIONS = [
  { value: "SCHEDULED", label: "Scheduled" },
  { value: "IN_PROGRESS", label: "In progress" },
  { value: "COMPLETED", label: "Completed" },
  { value: "CANCELLED", label: "Cancelled" },
];

export function MaintenanceView() {
  const { filters, setFilter, reset, activeCount } = useUrlFilters(FILTER_KEYS);

  const fleet = useMachineSummary();
  const upcoming = useUpcomingMaintenance({ page_size: 6 });
  const recent = useMaintenanceRecords({ status: "COMPLETED", page_size: 6 });
  const machineOptions = useMachineOptions();

  const tableState = useServerTableState();
  const records = useMaintenanceRecords({
    status: filters.status as MaintenanceStatus | undefined,
    machine_id: filters.machine_id,
    ...tableState.queryFilters,
  });
  const columns = useMemo(() => maintenanceColumns(), []);
  const table = useServerTable({ columns, state: tableState, page: records.data });

  return (
    <>
      <PageHeader
        title="Maintenance"
        description="Scheduled, in-progress and completed service work across the fleet."
        crumbs={[{ label: "Operations", href: "/dashboard" }]}
        meta={<RefreshingIndicator active={records.isRefreshing} />}
      />

      <section aria-labelledby="maintenance-kpis" className="mb-4">
        <h2 id="maintenance-kpis" className="sr-only">
          Maintenance summary
        </h2>
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-3">
          <QueryBoundary
            query={fleet}
            loadingLabel="Loading fleet summary"
            skeleton={<KpiCardSkeleton />}
            errorTitle="Unable to load the fleet summary."
          >
            {(data) => (
              <StatCard
                label="Machines due"
                value={formatNumber(data.maintenance_due_count)}
                context={`of ${formatNumber(data.total_machines)} machines`}
                tone={data.maintenance_due_count > 0 ? "warn" : "good"}
                statusLabel={data.maintenance_due_count > 0 ? "Attention" : "Clear"}
              />
            )}
          </QueryBoundary>

          <QueryBoundary
            query={upcoming}
            loadingLabel="Loading upcoming maintenance"
            skeleton={<KpiCardSkeleton />}
            errorTitle="Unable to load upcoming maintenance."
            renderEmptyAsContent
          >
            {(page) => (
              <StatCard
                label="Upcoming jobs"
                value={formatNumber(page.pagination.total)}
                context="Scheduled or in progress"
              />
            )}
          </QueryBoundary>

          <QueryBoundary
            query={recent}
            loadingLabel="Loading completed maintenance"
            skeleton={<KpiCardSkeleton />}
            errorTitle="Unable to load completed maintenance."
            renderEmptyAsContent
          >
            {(page) => (
              <StatCard
                label="Completed jobs"
                value={formatNumber(page.pagination.total)}
                context="Across all machines"
              />
            )}
          </QueryBoundary>
        </div>
      </section>

      <div className="mb-4 grid grid-cols-1 gap-4 lg:grid-cols-2">
        <Section title="Upcoming" description="Soonest first">
          <QueryBoundary
            query={upcoming}
            loadingLabel="Loading upcoming maintenance"
            skeleton={<ListSkeleton rows={4} />}
            errorTitle="Unable to load upcoming maintenance."
            emptyTitle="Nothing scheduled"
            emptyMessage="No maintenance is booked for any machine."
            emptyIcon="mdi:calendar-blank-outline"
            compact
            renderEmptyAsContent
          >
            {(page) =>
              page.data.length === 0 ? (
                <EmptyState
                  title="Nothing scheduled"
                  message="No maintenance is booked for any machine."
                  icon="mdi:calendar-blank-outline"
                  compact
                />
              ) : (
                <MaintenanceList records={page.data} />
              )
            }
          </QueryBoundary>
        </Section>

        <Section title="Recently completed" description="Most recent first">
          <QueryBoundary
            query={recent}
            loadingLabel="Loading completed maintenance"
            skeleton={<ListSkeleton rows={4} />}
            errorTitle="Unable to load completed maintenance."
            renderEmptyAsContent
          >
            {(page) =>
              page.data.length === 0 ? (
                <EmptyState
                  title="No completed work"
                  message="No maintenance has been completed yet."
                  icon="mdi:history"
                  compact
                />
              ) : (
                <MaintenanceList records={page.data} />
              )
            }
          </QueryBoundary>
        </Section>
      </div>

      <FilterBar onReset={reset} activeCount={activeCount}>
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
        title="All maintenance records"
        description="Every job, with its machine, technician and cost"
        flush
        actions={<RefreshingIndicator active={records.isRefreshing} />}
      >
        <QueryBoundary
          query={records}
          loadingLabel="Loading maintenance records"
          skeleton={<TableSkeleton columns={7} />}
          errorTitle="Unable to load maintenance records."
          renderEmptyAsContent
        >
          {(page) => (
            <>
              <DataTable
                table={table.table}
                caption="Maintenance records for the selected filters"
                empty={
                  <EmptyState
                    title="No maintenance records found"
                    message="No jobs match the selected status or machine."
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

function MaintenanceList({ records }: { records: MaintenanceRecord[] }) {
  return (
    <ul className="divide-border-base/70 divide-y">
      {records.map((record) => (
        <li key={record.id} className="py-2.5 first:pt-0 last:pb-0">
          <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
            <StatusBadge tone={maintenanceStatusTone(record.status)} size="sm">
              {record.status_label}
            </StatusBadge>
            <span className="text-foreground text-sm font-medium">{record.machine_code}</span>
            <span className="text-muted text-sm">{record.maintenance_type_label}</span>
            {record.is_overdue && (
              <StatusBadge tone="critical" size="sm">
                Overdue
              </StatusBadge>
            )}
          </div>
          <p className="text-muted mt-1 text-xs">{record.description}</p>
          <div className="text-subtle mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px]">
            <span>
              <Icon name="mdi:calendar" size={11} className="mr-1 inline align-[-1px]" />
              {formatDate(record.scheduled_date)}
            </span>
            <span>
              <Icon
                name="mdi:account-wrench-outline"
                size={11}
                className="mr-1 inline align-[-1px]"
              />
              {formatText(record.technician)}
            </span>
            {record.downtime_minutes > 0 && (
              <span>{formatMinutes(record.downtime_minutes)} down</span>
            )}
          </div>
        </li>
      ))}
    </ul>
  );
}

export function MaintenanceFallback() {
  return (
    <Card className="p-6">
      <Skeleton className="h-4 w-40" />
      <Skeleton className="mt-4 h-32 w-full" />
    </Card>
  );
}
