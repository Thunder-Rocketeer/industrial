"use client";

/**
 * Primary navigation (spec sections 1 and 2).
 *
 * One component serves the persistent desktop rail and the mobile drawer,
 * because two copies of a nav list drift: a route gets added to one and not the
 * other, and nobody notices until a phone is the only device to hand.
 *
 * Accessibility notes:
 *  - `aria-current="page"` marks the active link. The active state is also
 *    carried by a left bar *and* a weight change, never colour alone.
 *  - Icons are decorative (`Icon` hides them by default); the visible text is
 *    the accessible name, which is what spec section 2 asks for.
 *  - The list is a real `<nav>` with a label, so a screen reader can jump to it.
 */
import Link from "next/link";
import { usePathname } from "next/navigation";

import { Icon } from "@/components/ui/Icon";
import { NAV_ITEMS, activeNavItem } from "@/lib/navigation";
import { cn } from "@/lib/utils/cn";
import { useAuth } from "@/providers/auth-provider";

export function SidebarNav({ onNavigate }: { onNavigate?: () => void }) {
  const pathname = usePathname();
  const { can, state } = useAuth();
  const active = activeNavItem(pathname);

  // While the session is still loading, show everything rather than flashing a
  // short list that grows a moment later. Nothing is exposed by this: each page
  // fetches through the API, which enforces the real permissions.
  const visible = NAV_ITEMS.filter((item) => state === "loading" || can(item.permission));

  return (
    <nav aria-label="Main" className="flex-1 overflow-y-auto px-2 py-3">
      <ul className="space-y-0.5">
        {visible.map((item) => {
          const isActive = active?.href === item.href;
          return (
            <li key={item.href}>
              <Link
                href={item.href}
                onClick={onNavigate}
                aria-current={isActive ? "page" : undefined}
                className={cn(
                  "group relative flex items-center gap-2.5 rounded px-2.5 py-2 text-sm transition-colors",
                  isActive
                    ? "bg-accent-soft text-accent font-semibold"
                    : "text-muted hover:bg-surface-sunken hover:text-foreground font-medium",
                )}
              >
                {/* A shape, not just a tint: the active item stays identifiable
                    in monochrome and for colour-vision deficiencies. */}
                <span
                  aria-hidden="true"
                  className={cn(
                    "absolute top-1.5 bottom-1.5 -left-2 w-0.5 rounded-r",
                    isActive ? "bg-accent" : "bg-transparent",
                  )}
                />
                <Icon name={item.icon} size={18} className="shrink-0" />
                <span className="truncate">{item.label}</span>
              </Link>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}

/** The brand block at the top of the sidebar. */
export function SidebarBrand() {
  return (
    <Link
      href="/dashboard"
      className="border-border-base flex items-center gap-2.5 border-b px-4 py-3.5"
    >
      <span
        className="bg-accent text-accent-fg flex size-7 shrink-0 items-center justify-center rounded"
        aria-hidden="true"
      >
        <Icon name="mdi:factory" size={17} />
      </span>
      <span className="min-w-0">
        <span className="text-foreground block truncate text-sm leading-tight font-semibold">
          Factory Operations
        </span>
        <span className="text-subtle block truncate text-[11px] leading-tight">
          Component manufacturing
        </span>
      </span>
    </Link>
  );
}

/** The persistent rail. Hidden below `lg`, where the drawer takes over. */
export function DesktopSidebar() {
  return (
    <aside className="border-border-base bg-surface hidden w-60 shrink-0 flex-col border-r lg:flex">
      <SidebarBrand />
      <SidebarNav />
      <SidebarFooter />
    </aside>
  );
}

function SidebarFooter() {
  return (
    <div className="border-border-base text-subtle border-t px-4 py-3 text-[11px]">
      <p>
        Data refreshes automatically. <span className="whitespace-nowrap">Times shown in UTC.</span>
      </p>
    </div>
  );
}
