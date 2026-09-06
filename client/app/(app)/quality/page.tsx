import type { Metadata } from "next";
import { Suspense } from "react";

import { QualityFallback, QualityView } from "./QualityView";

/** `/quality` (spec section 21). Suspense wraps the `useSearchParams` reader. */
export const metadata: Metadata = {
  title: "Quality",
  description: "Defect rates, first-pass yield and defect analysis.",
};

export default function QualityPage() {
  return (
    <Suspense fallback={<QualityFallback />}>
      <QualityView />
    </Suspense>
  );
}
