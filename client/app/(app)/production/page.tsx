import type { Metadata } from "next";
import { Suspense } from "react";

import { ProductionFallback, ProductionView } from "./ProductionView";

/**
 * `/production` (spec section 20).
 *
 * The Suspense boundary is required, not decorative: `ProductionView` reads the
 * query string through `useSearchParams`, and Next.js needs a boundary around
 * any component that does so, or the whole route is forced out of static
 * rendering at build time.
 */
export const metadata: Metadata = {
  title: "Production",
  description: "Production output against plan and target.",
};

export default function ProductionPage() {
  return (
    <Suspense fallback={<ProductionFallback />}>
      <ProductionView />
    </Suspense>
  );
}
