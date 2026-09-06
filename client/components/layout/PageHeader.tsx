"use client";

/**
 * Page title, breadcrumb and page-level actions (spec sections 1 and 3).
 *
 * Renders the page's single `h1`. Every route uses this, so the heading
 * hierarchy is consistent by construction: `h1` here, `h2` on each `Section`,
 * `h3` inside them (spec section 18, WCAG 1.3.1).
 *
 * The breadcrumb is omitted on top-level pages. A one-item breadcrumb that just
 * repeats the title is noise, and an "aria-label: breadcrumb" landmark wrapping
 * a single non-link is worse than none.
 */
import Link from "next/link";
import type { ReactNode } from "react";

import { Icon } from "@/components/ui/Icon";

export interface Crumb {
  label: string;
  href?: string;
}

export function PageHeader({
  title,
  description,
  crumbs,
  actions,
  meta,
}: {
  title: string;
  description?: string;
  /** Ancestors only; the current page's title is appended automatically. */
  crumbs?: Crumb[];
  /** Controls: filters, refresh, export. */
  actions?: ReactNode;
  /** Secondary line under the title: last-updated, context, counts. */
  meta?: ReactNode;
}) {
  return (
    <div className="mb-4 flex flex-col gap-3 sm:mb-5">
      {crumbs && crumbs.length > 0 && (
        <nav aria-label="Breadcrumb">
          <ol className="text-subtle flex flex-wrap items-center gap-1 text-xs">
            {crumbs.map((crumb) => (
              <li key={crumb.label} className="flex items-center gap-1">
                {crumb.href ? (
                  <Link
                    href={crumb.href}
                    className="hover:text-foreground underline-offset-2 hover:underline"
                  >
                    {crumb.label}
                  </Link>
                ) : (
                  <span>{crumb.label}</span>
                )}
                <Icon name="mdi:chevron-right" size={13} className="opacity-60" />
              </li>
            ))}
            <li>
              {/* `aria-current="page"` marks the end of the trail. */}
              <span aria-current="page" className="text-muted font-medium">
                {title}
              </span>
            </li>
          </ol>
        </nav>
      )}

      <div className="flex flex-wrap items-start justify-between gap-x-4 gap-y-3">
        <div className="min-w-0">
          <h1 className="text-foreground truncate text-lg font-semibold tracking-tight sm:text-xl">
            {title}
          </h1>
          {description && <p className="text-subtle mt-1 text-sm">{description}</p>}
          {meta && <div className="mt-2">{meta}</div>}
        </div>
        {actions && <div className="flex shrink-0 flex-wrap items-center gap-2">{actions}</div>}
      </div>
    </div>
  );
}
