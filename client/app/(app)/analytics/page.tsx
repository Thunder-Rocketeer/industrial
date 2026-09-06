import type { Metadata } from "next";
import { Suspense } from "react";

import { AnalyticsFallback, AnalyticsView } from "./AnalyticsView";

/** `/analytics` (spec section 24). Suspense wraps the `useSearchParams` reader. */
export const metadata: Metadata = {
  title: "Analytics",
  description: "OEE, production efficiency and defect analysis.",
};

export default function AnalyticsPage() {
  return (
    <Suspense fallback={<AnalyticsFallback />}>
      <AnalyticsView />
    </Suspense>
  );
}
