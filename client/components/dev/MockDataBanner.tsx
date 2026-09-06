"use client";

/**
 * Installs the development mock adapter and says so, visibly (spec section 30).
 *
 * The banner is the point. A mock layer that is invisible is the one that ends
 * up in a demo, a screenshot or a bug report, with everyone in the room
 * believing the numbers. This renders a permanent, unmissable notice for as
 * long as fixtures are being served.
 *
 * In a production build `areApiMocksEnabled()` is false, this component renders
 * nothing, and the fixture modules are dropped from the bundle by the dynamic
 * import inside `installApiMocks`.
 */
import { useEffect, useState } from "react";

import { apiClient } from "@/lib/api/client";
import { areApiMocksEnabled, installApiMocks } from "@/lib/api/mock/install";

export function MockDataBanner() {
  const [active, setActive] = useState(false);

  useEffect(() => {
    if (!areApiMocksEnabled()) {
      return;
    }
    let cancelled = false;
    void installApiMocks(apiClient).then((installed) => {
      if (!cancelled) {
        setActive(installed);
      }
    });
    return () => {
      cancelled = true;
    };
  }, []);

  if (!active) {
    return null;
  }

  return (
    <div role="status" data-testid="mock-data-banner">
      <strong>Mock data.</strong> Some panels are served from local fixtures, not the backend. Set{" "}
      <code>NEXT_PUBLIC_ENABLE_API_MOCKS=false</code> to disable.
    </div>
  );
}
