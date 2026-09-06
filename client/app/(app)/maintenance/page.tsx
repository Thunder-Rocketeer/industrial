import type { Metadata } from "next";
import { Suspense } from "react";

import { MaintenanceFallback, MaintenanceView } from "./MaintenanceView";

/** `/maintenance` (spec section 26). Suspense wraps the `useSearchParams` reader. */
export const metadata: Metadata = {
  title: "Maintenance",
  description: "Scheduled and completed service work across the fleet.",
};

export default function MaintenancePage() {
  return (
    <Suspense fallback={<MaintenanceFallback />}>
      <MaintenanceView />
    </Suspense>
  );
}
