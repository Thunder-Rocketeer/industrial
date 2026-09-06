import type { Metadata } from "next";

import { DashboardView } from "./DashboardView";

/**
 * `/dashboard` (spec sections 3–12).
 *
 * A Server Component whose only job is metadata and mounting the client view
 * (spec section 35). The interactive, query-driven part is `DashboardView`, so
 * the client boundary starts there rather than at the route.
 */
export const metadata: Metadata = {
  title: "Dashboard",
  description: "Factory production, quality, inventory and machine status.",
};

export default function DashboardPage() {
  return <DashboardView />;
}
