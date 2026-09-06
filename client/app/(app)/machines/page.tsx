import type { Metadata } from "next";
import { Suspense } from "react";

import { MachinesFallback, MachinesView } from "./MachinesView";

/** `/machines` (spec section 23). Suspense wraps the `useSearchParams` reader. */
export const metadata: Metadata = {
  title: "Machines",
  description: "Fleet status, utilization and downtime.",
};

export default function MachinesPage() {
  return (
    <Suspense fallback={<MachinesFallback />}>
      <MachinesView />
    </Suspense>
  );
}
