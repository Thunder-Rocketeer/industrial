"use client";

/**
 * `/machines/{id}` (spec section 23).
 *
 * One machine: its current state, its production statistics for the window, its
 * OEE breakdown, and its maintenance history.
 *
 * The OEE terms come from the detail endpoint, already calculated. Showing all
 * three beside the composite is what makes the page actionable -- an
 * availability of 61% points at breakdowns, a performance of 61% points at
 * cycle times, and the single OEE number distinguishes neither (spec section 11).
 */
import { QueryBoundary, RefreshingIndicator } from "@/components/data/QueryBoundary";
import { OeeBreakdown } from "@/components/dashboard/Gauges";
import { StatCard } from "@/components/dashboard/KpiCard";
import { PageHeader } from "@/components/layout/PageHeader";
import { ButtonLink } from "@/components/ui/Button";
import { Card, Section, Stat } from "@/components/ui/Card";
import { Icon } from "@/components/ui/Icon";
import { StatusBadge, machineStatusTone, maintenanceStatusTone } from "@/components/ui/Status";
import { EmptyState, KpiCardSkeleton, ListSkeleton, Skeleton } from "@/components/ui/States";
import { useMachine } from "@/hooks/queries/useMachines";
import {
  formatCurrency,
  formatDate,
  formatDateTime,
  formatMinutes,
  formatNumber,
  formatPercentage,
  formatRelativeDays,
  formatText,
} from "@/lib/utils/format";
import type { MaintenanceRecord } from "@/types/machines";

export function MachineDetailView({ machineId }: { machineId: string }) {
  const machine = useMachine(machineId);

  const title = machine.data ? `${machine.data.code} — ${machine.data.name}` : "Machine";

  return (
    <>
      <PageHeader
        title={title}
        crumbs={[
          { label: "Operations", href: "/dashboard" },
          { label: "Machines", href: "/machines" },
        ]}
        description={machine.data ? machine.data.machine_type_label : undefined}
        meta={<RefreshingIndicator active={machine.isRefreshing} />}
        actions={
          <ButtonLink href="/machines" size="sm" variant="secondary" icon="mdi:arrow-left">
            All machines
          </ButtonLink>
        }
      />

      <QueryBoundary
        query={machine}
        loadingLabel="Loading machine detail"
        skeleton={
          <div className="space-y-4">
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-4">
              {Array.from({ length: 4 }).map((_, index) => (
                <KpiCardSkeleton key={index} />
              ))}
            </div>
            <Card className="p-4">
              <Skeleton className="h-24 w-full" />
            </Card>
          </div>
        }
        errorTitle="Unable to load this machine."
        emptyTitle="Machine not found"
      >
        {(data) => (
          <>
            {/* Current state */}
            <div className="mb-4 grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-4">
              <Card className="flex flex-col p-4">
                <h3 className="text-subtle text-xs font-medium">Status</h3>
                <div className="mt-2">
                  <StatusBadge tone={machineStatusTone(data.status)} withIcon>
                    {data.status_label}
                  </StatusBadge>
                </div>
                <p className="text-muted mt-2 text-xs">
                  {data.current_component_name
                    ? `Running ${data.current_component_name}`
                    : "No component assigned"}
                </p>
              </Card>

              <StatCard
                label="Utilization"
                value={formatPercentage(data.utilization_percentage)}
                context={`${formatMinutes(data.total_downtime_minutes)} downtime`}
              />
              <StatCard label="Line" value={data.line_code} context={data.line_name} />
              <StatCard
                label="Next service"
                value={formatDate(data.next_maintenance_date)}
                context={
                  data.days_until_maintenance === null
                    ? "Not scheduled"
                    : formatRelativeDays(data.days_until_maintenance)
                }
                tone={data.maintenance_due ? "warn" : undefined}
                statusLabel={data.maintenance_due ? "Due" : undefined}
              />
            </div>

            {/* Production and OEE */}
            <div className="mb-4 grid grid-cols-1 gap-4 lg:grid-cols-2">
              <Section title="Production" description="Over the requested window">
                {/* `run_count` is the record count for this machine's window;
                    zero means nothing ran, which is a fact worth stating rather
                    than rendering as a grid of zeroes. */}
                {data.production.run_count > 0 ? (
                  <dl className="grid grid-cols-2 gap-4 sm:grid-cols-3">
                    <Stat
                      label="Produced"
                      value={formatNumber(data.production.produced_quantity)}
                      hint="units"
                    />
                    <Stat
                      label="Accepted"
                      value={formatNumber(data.production.accepted_quantity)}
                      hint="units"
                    />
                    <Stat
                      label="Rejected"
                      value={formatNumber(data.production.rejected_quantity)}
                      hint="units"
                    />
                    <Stat
                      label="Operating time"
                      value={formatMinutes(data.production.operating_minutes)}
                    />
                    <Stat
                      label="Downtime"
                      value={formatMinutes(data.production.downtime_minutes)}
                    />
                    <Stat label="Production runs" value={formatNumber(data.production.run_count)} />
                  </dl>
                ) : (
                  <EmptyState
                    title="No production recorded"
                    message="This machine produced nothing in the selected window."
                    compact
                  />
                )}
              </Section>

              <Section
                title="OEE"
                description="Effectiveness for this machine over the same window"
              >
                {data.production.run_count > 0 ? (
                  <OeeBreakdown
                    compact
                    oee={data.production.oee_percentage}
                    availability={data.production.availability_percentage}
                    performance={data.production.performance_percentage}
                    quality={data.production.quality_percentage}
                  />
                ) : (
                  <EmptyState
                    title="No OEE available"
                    message="OEE needs production records to calculate."
                    compact
                  />
                )}
              </Section>
            </div>

            {/* Maintenance */}
            <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
              <Section title="Upcoming maintenance" description="Scheduled and in progress">
                {data.upcoming_maintenance.length === 0 ? (
                  <EmptyState
                    title="Nothing scheduled"
                    message="No maintenance is booked for this machine."
                    icon="mdi:calendar-blank-outline"
                    compact
                  />
                ) : (
                  <MaintenanceList records={data.upcoming_maintenance} />
                )}
              </Section>

              <Section title="Recent maintenance" description="Most recent work first">
                {data.recent_maintenance.length === 0 ? (
                  <EmptyState
                    title="No maintenance history"
                    message="No completed work is recorded for this machine."
                    icon="mdi:history"
                    compact
                  />
                ) : (
                  <MaintenanceList records={data.recent_maintenance} />
                )}
              </Section>
            </div>
          </>
        )}
      </QueryBoundary>
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
            <span className="text-foreground text-sm font-medium">
              {record.maintenance_type_label}
            </span>
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
            {record.cost !== null && <span>{formatCurrency(record.cost)}</span>}
            {record.completed_at && <span>Completed {formatDateTime(record.completed_at)}</span>}
          </div>
        </li>
      ))}
    </ul>
  );
}

export function MachineDetailFallback() {
  return (
    <Card className="p-6">
      <Skeleton className="h-4 w-40" />
      <ListSkeleton rows={3} />
    </Card>
  );
}
