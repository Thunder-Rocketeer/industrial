/**
 * The application's navigation map (spec section 2).
 *
 * One list, used by the desktop sidebar, the mobile drawer and the breadcrumb,
 * so the three cannot disagree about what exists or what it is called.
 *
 * **`permission` is a UX hint, not a security control.** Hiding a link stops a
 * user wandering into a page that will only 403; it does not protect anything.
 * The backend checks every request independently, so a user who edits client
 * state, guesses the URL, or calls the API directly gets a 403 either way (spec
 * section 2 and section 12 of the Phase 4 brief).
 */

export interface NavItem {
  href: string;
  label: string;
  /** Iconify name. Rendered decoratively -- the label is the accessible name. */
  icon: string;
  /** Backend permission that makes this page useful. UX only. */
  permission: string;
  /** One-line purpose, used as the link's title and in the mobile drawer. */
  description: string;
}

export const NAV_ITEMS: NavItem[] = [
  {
    href: "/dashboard",
    label: "Dashboard",
    icon: "mdi:view-dashboard-outline",
    permission: "dashboard:read",
    description: "Factory status at a glance",
  },
  {
    href: "/production",
    label: "Production",
    icon: "mdi:factory",
    permission: "production:read",
    description: "Output, targets and shift records",
  },
  {
    href: "/quality",
    label: "Quality",
    icon: "mdi:magnify-scan",
    permission: "quality:read",
    description: "Defects, rejection rates and first-pass yield",
  },
  {
    href: "/inventory",
    label: "Inventory",
    icon: "mdi:package-variant-closed",
    permission: "inventory:read",
    description: "Stock levels and reorder alerts",
  },
  {
    href: "/machines",
    label: "Machines",
    icon: "mdi:robot-industrial-outline",
    permission: "machines:read",
    description: "Fleet status, utilization and downtime",
  },
  {
    href: "/analytics",
    label: "Analytics",
    icon: "mdi:chart-timeline-variant",
    permission: "analytics:read",
    description: "OEE, efficiency and defect analysis",
  },
  {
    href: "/alerts",
    label: "Alerts",
    icon: "mdi:bell-alert-outline",
    permission: "alerts:read",
    description: "Open and resolved operational alerts",
  },
  {
    href: "/maintenance",
    label: "Maintenance",
    icon: "mdi:wrench-outline",
    permission: "maintenance:read",
    description: "Scheduled and completed service work",
  },
];

/**
 * The nav item a path belongs to.
 *
 * Prefix matching, so `/machines/abc-123` still highlights "Machines". The
 * longest match wins, which keeps a future `/machines/settings` from resolving
 * to the wrong parent.
 */
export function activeNavItem(pathname: string): NavItem | undefined {
  return NAV_ITEMS.filter(
    (item) => pathname === item.href || pathname.startsWith(`${item.href}/`),
  ).sort((a, b) => b.href.length - a.href.length)[0];
}
