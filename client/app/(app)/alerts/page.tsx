import type { Metadata } from "next";
import { Suspense } from "react";

import { AlertsFallback, AlertsView } from "./AlertsView";

/** `/alerts` (spec section 25). Suspense wraps the `useSearchParams` reader. */
export const metadata: Metadata = {
  title: "Alerts",
  description: "Operational alerts across machines, inventory and production.",
};

export default function AlertsPage() {
  return (
    <Suspense fallback={<AlertsFallback />}>
      <AlertsView />
    </Suspense>
  );
}
