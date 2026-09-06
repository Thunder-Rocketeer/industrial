"use client";

/**
 * `/machines` (spec sections 8 and 23).
 *
 * The fleet, its status distribution, and a table that opens a machine.
 *
 * The machine list is unpaginated by design -- a factory has a dozen machines,
 * not a dataset -- so this page renders a plain table rather than going through
 * `useServerTable`. Using the server-driven controller here would add pagination
 * chrome for a single page of twelve rows.
 *
 * Status is scannable: a dot, the word, and utilization as a number, in that
 * order across the row. The word is what carries the meaning (spec section 8).
 */
import { useRouter } from "next/navigation";
import { useMemo } from "react";

import { QueryBoundary, RefreshingIndicator } from "@/components/data/QueryBoundary";
import { StatusDistribution } from "@/components/dashboard/Gauges";
import { StatCard } from "@/components/dashboard/KpiCard";
import { FilterBar, SelectFilter } from "@/components/filters/Filters";
import { PageHeader } from "@/components/layout/PageHeader";
import { Card, Section, Stat } from "@/components/ui/Card";
import { StatusBadge, StatusDot, machineStatusTone } from "@/components/ui/Status";
import { EmptyState, KpiCardSkeleton, Skeleton, TableSkeleton } from "@/components/ui/States";
import { useMachineSummary, useMachines, usePrefetchMachine } from "@/hooks/queries/useMachines";
import { useLineOptions } from "@/hooks/useFilterOptions";
import { useUrlFilters } from "@/hooks/useUrlFilters";
import {
  formatDate,
  formatMinutes,
  formatNumber,
  formatPercentage,
  formatText,
} from "@/lib/utils/format";
import type { MachineStatus } from "@/types/common";
import type { MachineSummary } from "@/types/machines";

const FILTER_KEYS = ["status", "line_id"] as const;

const STATUS_OPTIONS = [
  { value: "RUNNING", label: "Running" },
  { value: "IDLE", label: "Idle" },
  { value: "MAINTENANCE", label: "Maintenance" },
  { value: "OFFLINE", label: "Offline" },
];

export function MachinesView() {
  const router = useRouter();
  const { filters, setFilter, reset, activeCount } = useUrlFilters(FILTER_KEYS);
  const prefetchMachine = usePrefetchMachine();

  const summary = useMachineSummary();
  const machines = useMachines({
    status: filters.status as MachineStatus | undefined,
    line_id: filters.line_id,
  });
  const lineOptions = useLineOptions({});

  return (
    <>
      <PageHeader
        title="Machines"
        description="Fleet status, utilization and downtime across all production lines."
        crumbs={[{ label: "Operations", href: "/dashboard" }]}
        meta={<RefreshingIndicator active={summary.isRefreshing || machines.isRefreshing} />}
      />

      <section aria-labelledby="machine-kpis" className="mb-4">
        <h2 id="machine-kpis" className="sr-only">
          Fleet summary
        </h2>
        <QueryBoundary
          query={summary}
          loadingLabel="Loading fleet summary"
          skeleton={
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-4">
              {Array.from({ length: 4 }).map((_, index) => (
                <KpiCardSkeleton key={index} />
              ))}
            </div>
          }
          errorTitle="Unable to load the fleet summary."
          emptyTitle="No machines configured"
        >
          {(data) => (
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-4">
              <StatCard
                label="Machines"
                value={formatNumber(data.total_machines)}
                context={`${formatNumber(data.running_count)} running now`}
              />
              <StatCard
                label="Availability"
                value={formatPercentage(data.availability_percentage)}
                context="Only running machines count as available"
                tone={
                  data.availability_percentage >= 80
                    ? "good"
                    : data.availability_percentage >= 60
                      ? "warn"
                      : "critical"
                }
                statusLabel={
                  data.availability_percentage >= 80
                    ? "Healthy"
                    : data.availability_percentage >= 60
                      ? "Warning"
                      : "Critical"
                }
              />
              <StatCard
                label="Average utilization"
                value={formatPercentage(data.average_utilization_percentage)}
                context="Across the whole fleet"
              />
              <StatCard
                label="Maintenance due"
                value={formatNumber(data.maintenance_due_count)}
                context="Within the attention window, or overdue"
                tone={data.maintenance_due_count > 0 ? "warn" : "good"}
                statusLabel={data.maintenance_due_count > 0 ? "Attention" : "Clear"}
              />
            </div>
          )}
        </QueryBoundary>
      </section>

      <div className="mb-4">
        <Section title="Status distribution" description="Where the fleet is right now">
          <QueryBoundary
            query={summary}
            loadingLabel="Loading status distribution"
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
            {(data) =>
              data.total_machines === 0 ? (
                <EmptyState title="No machines configured" compact />
              ) : (
                <div className="space-y-4">
                  <StatusDistribution
                    total={data.total_machines}
                    itemNoun="machines"
                    segments={data.status_breakdown.map((entry) => ({
                      label: entry.status_label,
                      count: entry.count,
                      tone: machineStatusTone(entry.status),
                    }))}
                  />
                  <dl className="border-border-base grid grid-cols-2 gap-4 border-t pt-3 sm:grid-cols-4">
                    <Stat label="Running" value={formatNumber(data.running_count)} />
                    <Stat label="Idle" value={formatNumber(data.idle_count)} />
                    <Stat label="Maintenance" value={formatNumber(data.maintenance_count)} />
                    <Stat label="Offline" value={formatNumber(data.offline_count)} />
                  </dl>
                </div>
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
          onChange={(value) => setFilter("status", value)}
        />
        <SelectFilter
          label="Line"
          value={filters.line_id}
          options={lineOptions.options}
          loading={lineOptions.isLoading}
          allLabel="All lines"
          onChange={(value) => setFilter("line_id", value)}
        />
      </FilterBar>

      <Section title="Fleet" description="Select a machine to see its detail" flush>
        <QueryBoundary
          query={machines}
          loadingLabel="Loading machines"
          skeleton={<TableSkeleton columns={7} />}
          errorTitle="Unable to load machines."
          emptyTitle="No machines match these filters"
          emptyMessage="Try clearing the status or line filter."
        >
          {(rows) => (
            <MachineTable
              machines={rows}
              onOpen={(machine) => router.push(`/machines/${machine.id}`)}
              onPrefetch={prefetchMachine}
            />
          )}
        </QueryBoundary>
      </Section>
    </>
  );
}

/**
 * The fleet table.
 *
 * Hand-rolled rather than TanStack, because the list is unpaginated and
 * unsorted server-side: there is no state for a table instance to hold. The
 * machine code is a `<button>` so the row is reachable by keyboard, and hover
 * or focus prefetches the detail so the page is warm before the click lands
 * (Phase 5's `usePrefetchMachine`).
 */
function MachineTable({
  machines,
  onOpen,
  onPrefetch,
}: {
  machines: MachineSummary[];
  onOpen: (machine: MachineSummary) => void;
  onPrefetch: (id: string) => void;
}) {
  const columns = useMemo(
    () => [
      "Machine",
      "Type",
      "Line",
      "Status",
      "Utilization",
      "Downtime",
      "Running",
      "Next service",
    ],
    [],
  );

  return (
    <div className="w-full overflow-x-auto">
      <table className="w-full border-collapse text-sm">
        <caption className="sr-only">
          Machines in the fleet, with status, utilization and downtime
        </caption>
        <thead>
          <tr>
            {columns.map((column) => (
              <th
                key={column}
                scope="col"
                className="border-border-base bg-surface-sunken/60 text-subtle border-b px-3 py-2 text-left text-xs font-medium whitespace-nowrap"
              >
                {column}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {machines.map((machine) => (
            <tr
              key={machine.id}
              className="border-border-base/60 hover:bg-surface-sunken/60 border-b last:border-b-0"
              onMouseEnter={() => onPrefetch(machine.id)}
            >
              <td className="px-3 py-2.5 whitespace-nowrap">
                <button
                  type="button"
                  onClick={() => onOpen(machine)}
                  onFocus={() => onPrefetch(machine.id)}
                  className="text-foreground hover:text-accent font-medium underline-offset-2 hover:underline"
                >
                  {machine.code}
                  <span className="sr-only">, open machine detail for {machine.name}</span>
                </button>
                <div className="text-subtle text-xs">{machine.name}</div>
              </td>
              <td className="text-muted px-3 py-2.5 whitespace-nowrap">
                {machine.machine_type_label}
              </td>
              <td className="text-muted px-3 py-2.5 whitespace-nowrap">{machine.line_name}</td>
              <td className="px-3 py-2.5 whitespace-nowrap">
                <span className="inline-flex items-center gap-1.5">
                  <StatusDot tone={machineStatusTone(machine.status)} />
                  <span className="text-foreground">{machine.status_label}</span>
                </span>
              </td>
              <td className="text-foreground px-3 py-2.5 whitespace-nowrap">
                {formatPercentage(machine.utilization_percentage)}
              </td>
              <td className="text-muted px-3 py-2.5 whitespace-nowrap">
                {formatMinutes(machine.total_downtime_minutes)}
              </td>
              <td className="text-muted px-3 py-2.5 whitespace-nowrap">
                {formatText(machine.current_component_name)}
              </td>
              <td className="px-3 py-2.5 whitespace-nowrap">
                <span className="flex items-center gap-2">
                  <span className="text-muted">{formatDate(machine.next_maintenance_date)}</span>
                  {machine.maintenance_due && (
                    <StatusBadge tone="warn" size="sm">
                      Due
                    </StatusBadge>
                  )}
                </span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function MachinesFallback() {
  return (
    <Card className="p-6">
      <Skeleton className="h-4 w-40" />
      <Skeleton className="mt-4 h-32 w-full" />
    </Card>
  );
}
