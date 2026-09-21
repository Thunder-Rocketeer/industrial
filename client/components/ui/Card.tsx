/**
 * Surfaces and section framing (spec section 32).
 *
 * One card style for the whole application: a 1px border, a flat surface, a 6px
 * radius. No shadow stack and no large radius -- both eat the horizontal space
 * that a dense operations screen needs, and a shadow implies a depth hierarchy
 * this UI does not have.
 *
 * `Section` pairs a card with a heading. The `headingLevel` prop is not
 * decoration: a page has one `h1`, its sections are `h2`, and panels nested
 * inside them are `h3`. Skipping a level breaks the document outline that a
 * screen-reader user navigates by (spec section 18, WCAG 1.3.1).
 */
import type { ElementType, ReactNode } from "react";

import { cn } from "@/lib/utils/cn";

export function Card({
  children,
  className,
  as: Component = "div",
}: {
  children: ReactNode;
  className?: string;
  as?: ElementType;
}) {
  return (
    <Component
      className={cn(
        "border-border-base bg-surface rounded-md border",
        // `min-w-0` so a wide child (a table, a chart) shrinks inside a grid
        // track instead of forcing the page to scroll sideways.
        "min-w-0",
        className,
      )}
    >
      {children}
    </Component>
  );
}

export interface SectionProps {
  title: string;
  /** Rendered under the title. Keep it to one line. */
  description?: string;
  /** Controls, filters or a link. Sits opposite the title. */
  actions?: ReactNode;
  headingLevel?: 2 | 3 | 4;
  /** Removes the body padding, for a table that should meet the card edge. */
  flush?: boolean;
  children: ReactNode;
  className?: string;
  /** Anchor target, so the page can be linked to this section. */
  id?: string;
}

export function Section({
  title,
  description,
  actions,
  headingLevel = 2,
  flush = false,
  children,
  className,
  id,
}: SectionProps) {
  const Heading = `h${headingLevel}` as ElementType;

  return (
    <Card as="section" className={cn("flex flex-col", className)}>
      <div
        className={cn(
          "border-border-base flex flex-wrap items-start justify-between gap-3 border-b px-4 py-3",
        )}
      >
        <div className="min-w-0">
          <Heading
            id={id}
            className="text-foreground text-sm font-semibold tracking-tight"
            // `scroll-mt` keeps the heading clear of the sticky header when a
            // skip link or an anchor jumps to it.
            style={{ scrollMarginTop: "5rem" }}
          >
            {title}
          </Heading>
          {description && <p className="text-subtle mt-0.5 text-xs">{description}</p>}
        </div>
        {actions && <div className="flex shrink-0 items-center gap-2">{actions}</div>}
      </div>
      <div className={cn("min-w-0 flex-1", flush ? "" : "p-4")}>{children}</div>
    </Card>
  );
}

/** A labelled figure, for the small stat rows beneath a chart or in a panel. */
export function Stat({
  label,
  value,
  hint,
  className,
}: {
  label: string;
  value: ReactNode;
  hint?: ReactNode;
  className?: string;
}) {
  /*
   * The hint lives inside the `<dd>`, not beside it.
   *
   * A `<dl>` may only contain `<dt>`/`<dd>` groups, and a wrapping `<div>` may
   * only contain those. A `<p>` sitting alongside them breaks the association
   * between the term and its description -- axe-core flags it as
   * `definition-list`, and a screen reader reading the list loses the hint. It
   * is a description of the value, so it belongs in the description.
   */
  return (
    <div className={cn("min-w-0", className)}>
      <dt className="text-subtle truncate text-xs">{label}</dt>
      <dd className="mt-0.5">
        <span className="text-foreground block text-lg font-semibold tracking-tight">{value}</span>
        {hint && <span className="text-subtle mt-0.5 block text-xs">{hint}</span>}
      </dd>
    </div>
  );
}
