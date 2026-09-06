"use client";

/**
 * The authenticated application shell (spec section 1).
 *
 * One shell for all eight pages: sidebar, header, and a main region. Pages
 * supply only their content, so navigation, the account menu, the alert badge
 * and the outage banner cannot differ between routes.
 *
 * Responsive behaviour (spec sections 1 and 37):
 *   - `lg` and up: persistent 240px rail beside the content.
 *   - below `lg`: rail hidden, a menu button opens the same nav in a drawer.
 *   - the main column is `min-w-0` throughout, which is what actually prevents
 *     a wide table or chart from pushing the page into horizontal scroll.
 */
import { useState, type ReactNode } from "react";

import { BackendUnavailable } from "@/components/data/BackendUnavailable";
import { AlertBell } from "@/components/layout/AlertBell";
import { DesktopSidebar, SidebarBrand, SidebarNav } from "@/components/layout/Sidebar";
import { UserMenu } from "@/components/layout/UserMenu";
import { IconButton } from "@/components/ui/Button";
import { Drawer } from "@/components/ui/Drawer";

export function AppShell({ children }: { children: ReactNode }) {
  const [navOpen, setNavOpen] = useState(false);

  return (
    <div className="bg-background flex min-h-dvh w-full">
      <DesktopSidebar />

      <Drawer open={navOpen} onClose={() => setNavOpen(false)} title="Navigation">
        <SidebarNav onNavigate={() => setNavOpen(false)} />
      </Drawer>

      {/* `min-w-0` on the column, not just the content: a grid/flex child
          defaults to `min-width: auto`, which lets a wide descendant expand it
          past the viewport. This one line is the difference between a table
          that scrolls inside its card and a page that scrolls sideways. */}
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="border-border-base bg-surface/95 sticky top-0 z-30 flex h-14 shrink-0 items-center gap-2 border-b px-3 backdrop-blur sm:px-4">
          <IconButton
            icon="mdi:menu"
            label="Open navigation menu"
            className="lg:hidden"
            onClick={() => setNavOpen(true)}
          />

          {/* The brand shows in the header only on small screens, where the
              sidebar that normally carries it is hidden. */}
          <div className="min-w-0 flex-1 lg:hidden">
            <MobileBrand />
          </div>
          <div className="hidden flex-1 lg:block" />

          <AlertBell />
          <UserMenu />
        </header>

        <main id="main-content" className="min-w-0 flex-1 px-3 py-4 sm:px-4 sm:py-5 lg:px-6">
          {/* One outage notice for the whole shell, rather than eight identical
              ones inside eight panels (spec section 14). */}
          <BackendUnavailable>{children}</BackendUnavailable>
        </main>
      </div>
    </div>
  );
}

function MobileBrand() {
  return (
    <span className="text-foreground block truncate text-sm font-semibold">Factory Operations</span>
  );
}

/** Re-exported so pages can compose a header without importing the sidebar. */
export { SidebarBrand };
