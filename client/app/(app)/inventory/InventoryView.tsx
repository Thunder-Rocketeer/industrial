"use client";

/**
 * `/inventory` (spec sections 9 and 22).
 *
 * Stock position, the items that need attention, and the full item table.
 *
 * **Stock health is not computed here.** The database derives `status` from the
 * quantity against the item's own minimum, reorder point and maximum, and the
 * backend sends both the code and a `status_label`. Comparing
 * `current_quantity` to `reorder_point` in a React component would be a second
 * implementation of that rule -- one that does not know about the maximum, the
 * per-item thresholds, or the overstock case (spec section 9).
 */
import { useMemo } from "react";

import { QueryBoundary, RefreshingIndicator } from "@/components/data/QueryBoundary";
import { StatusDistribution } from "@/components/dashboard/Gauges";
import { StatCard } from "@/components/dashboard/KpiCard";
import { FilterBar, SelectFilter } from "@/components/filters/Filters";
import { PageHeader } from "@/components/layout/PageHeader";
import { DataTable, TablePagination } from "@/components/tables/DataTable";
import { Card, Section, Stat } from "@/components/ui/Card";
import { Icon } from "@/components/ui/Icon";
import { StatusBadge, inventoryStatusTone } from "@/components/ui/Status";
import {
  EmptyState,
  KpiCardSkeleton,
  ListSkeleton,
  Skeleton,
  TableSkeleton,
} from "@/components/ui/States";
import {
  useInventoryAlerts,
  useInventoryItems,
  useInventorySummary,
} from "@/hooks/queries/useInventory";
import { useComponentOptions } from "@/hooks/useFilterOptions";
import { useServerTable, useServerTableState } from "@/hooks/useServerTable";
import { useUrlFilters } from "@/hooks/useUrlFilters";
import { inventoryColumns } from "@/lib/table/columns";
import { formatCurrency, formatNumber, formatPercentage, formatQuantity } from "@/lib/utils/format";
import type { InventoryStatus } from "@/types/common";

const FILTER_KEYS = ["status", "component_id"] as const;

const STATUS_OPTIONS = [
  { value: "CRITICAL", label: "Critical" },
  { value: "LOW", label: "Low" },
  { value: "HEALTHY", label: "Healthy" },
  { value: "OVERSTOCKED", label: "Overstocked" },
];

export function InventoryView() {
  const { filters, setFilter, reset, activeCount } = useUrlFilters(FILTER_KEYS);

  const summary = useInventorySummary();
  const alerts = useInventoryAlerts();
  const componentOptions = useComponentOptions({});

  const tableState = useServerTableState({ initialSorting: [{ id: "status", desc: false }] });
  const items = useInventoryItems({
    status: filters.status as InventoryStatus | undefined,
    component_id: filters.component_id,
    ...tableState.queryFilters,
  });
  const columns = useMemo(() => inventoryColumns(), []);
  const table = useServerTable({ columns, state: tableState, page: items.data });

  return (
    <>
      <PageHeader
        title="Inventory"
        description="Stock levels, reorder points and material health across the factory."
        crumbs={[{ label: "Operations", href: "/dashboard" }]}
        meta={<RefreshingIndicator active={summary.isRefreshing || items.isRefreshing} />}
      />

      <section aria-labelledby="inventory-kpis" className="mb-4">
        <h2 id="inventory-kpis" className="sr-only">
          Inventory summary
        </h2>
        <QueryBoundary
          query={summary}
          loadingLabel="Loading inventory summary"
          skeleton={
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-4">
              {Array.from({ length: 4 }).map((_, index) => (
                <KpiCardSkeleton key={index} />
              ))}
            </div>
          }
          errorTitle="Unable to load the inventory summary."
        >
          {(data) => (
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-4">
              <StatCard
                label="Total items"
                value={formatNumber(data.total_items)}
                context={`${formatNumber(data.healthy_count)} healthy`}
              />
              <StatCard
                label="Needs attention"
                value={formatNumber(data.items_requiring_attention)}
                context={`${formatNumber(data.critical_count)} critical, ${formatNumber(data.low_count)} low`}
                tone={data.critical_count > 0 ? "critical" : data.low_count > 0 ? "warn" : "good"}
                statusLabel={
                  data.critical_count > 0 ? "Critical" : data.low_count > 0 ? "Warning" : "Healthy"
                }
              />
              <StatCard
                label="Stock health"
                value={formatPercentage(data.health_percentage)}
                context="Share of items in a healthy state"
              />
              <StatCard
                label="Stock value"
                value={
                  // Null when any item has no unit cost: a partial sum is not a
                  // total, and the backend says so rather than guessing.
                  data.total_stock_value === null
                    ? "Unavailable"
                    : formatCurrency(data.total_stock_value)
                }
                context={
                  data.total_stock_value === null
                    ? "Some items have no unit cost recorded"
                    : "At recorded unit cost"
                }
              />
            </div>
          )}
        </QueryBoundary>
      </section>

      <div className="mb-4 grid grid-cols-1 gap-4 lg:grid-cols-2">
        <Section title="Stock position" description="Every material by health state">
          <QueryBoundary
            query={summary}
            loadingLabel="Loading stock position"
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
              data.total_items === 0 ? (
                <EmptyState title="No inventory items" compact />
              ) : (
                <div className="space-y-4">
                  <StatusDistribution
                    total={data.total_items}
                    itemNoun="items"
                    segments={data.status_breakdown.map((entry) => ({
                      label: entry.status_label,
                      count: entry.count,
                      tone: inventoryStatusTone(entry.status),
                    }))}
                  />
                  <dl className="border-border-base grid grid-cols-2 gap-4 border-t pt-3">
                    <Stat
                      label="Below reorder point"
                      value={formatNumber(data.items_requiring_attention)}
                    />
                    <Stat label="Overstocked" value={formatNumber(data.overstocked_count)} />
                  </dl>
                </div>
              )
            }
          </QueryBoundary>
        </Section>

        <Section title="Stock alerts" description="Items at or below their reorder point">
          <QueryBoundary
            query={alerts}
            loadingLabel="Loading stock alerts"
            skeleton={<ListSkeleton rows={4} />}
            errorTitle="Unable to load stock alerts."
            emptyTitle="No stock alerts"
            emptyMessage="Every material is above its reorder point."
            emptyIcon="mdi:check-circle-outline"
            compact
          >
            {(data) => (
              <ul className="divide-border-base/70 divide-y">
                {data.slice(0, 8).map((alert) => (
                  <li key={alert.id} className="flex items-start gap-3 py-2.5 first:pt-0">
                    <Icon
                      name="mdi:package-variant"
                      size={16}
                      className={
                        alert.status === "CRITICAL" ? "text-critical mt-0.5" : "text-warn mt-0.5"
                      }
                    />
                    <div className="min-w-0 flex-1">
                      <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
                        <span className="text-foreground text-sm font-medium">{alert.name}</span>
                        <StatusBadge tone={inventoryStatusTone(alert.status)} size="sm">
                          {alert.status_label}
                        </StatusBadge>
                      </div>
                      <p className="text-subtle mt-0.5 text-xs">
                        {formatQuantity(alert.current_quantity, alert.unit)} on hand · reorder at{" "}
                        {formatQuantity(alert.reorder_point, alert.unit)}
                      </p>
                    </div>
                  </li>
                ))}
              </ul>
            )}
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
      </FilterBar>

      <Section
        title="Materials"
        description="Stock on hand against minimum and reorder levels"
        flush
        actions={<RefreshingIndicator active={items.isRefreshing} />}
      >
        <QueryBoundary
          query={items}
          loadingLabel="Loading inventory items"
          skeleton={<TableSkeleton columns={6} />}
          errorTitle="Unable to load inventory items."
          renderEmptyAsContent
        >
          {(page) => (
            <>
              <DataTable
                table={table.table}
                caption="Inventory items for the selected filters"
                empty={
                  <EmptyState
                    title="No materials found"
                    message="No items match the selected status or component."
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
                disabled={items.isRefreshing}
              />
            </>
          )}
        </QueryBoundary>
      </Section>
    </>
  );
}

export function InventoryFallback() {
  return (
    <Card className="p-6">
      <Skeleton className="h-4 w-40" />
      <Skeleton className="mt-4 h-32 w-full" />
    </Card>
  );
}
