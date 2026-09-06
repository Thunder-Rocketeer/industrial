import type { Metadata } from "next";
import { Suspense } from "react";

import { InventoryFallback, InventoryView } from "./InventoryView";

/** `/inventory` (spec section 22). Suspense wraps the `useSearchParams` reader. */
export const metadata: Metadata = {
  title: "Inventory",
  description: "Stock levels, reorder points and material health.",
};

export default function InventoryPage() {
  return (
    <Suspense fallback={<InventoryFallback />}>
      <InventoryView />
    </Suspense>
  );
}
