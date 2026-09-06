/**
 * Buttons and button-styled links (spec section 32).
 *
 * Two accessibility rules are enforced by the types rather than by review:
 *
 *   - An icon-only button must pass `label`. Without it the button has no
 *     accessible name and a screen reader announces "button" (WCAG 4.1.2).
 *     `IconButton` requires it.
 *   - A link that navigates is an `<a>`, and a control that acts is a
 *     `<button>`. They are not interchangeable: only the link supports
 *     middle-click, "open in new tab" and the browser's own affordances, and
 *     only the button responds to Space.
 *
 * The focus ring comes from `globals.css`, so it cannot be forgotten here.
 */
import Link from "next/link";
import type { ButtonHTMLAttributes, ReactNode } from "react";

import { Icon } from "@/components/ui/Icon";
import { cn } from "@/lib/utils/cn";

type Variant = "primary" | "secondary" | "ghost" | "danger";
type Size = "sm" | "md";

const VARIANTS: Record<Variant, string> = {
  primary: "bg-accent text-accent-fg hover:opacity-90 border border-transparent",
  secondary: "bg-surface text-foreground border border-border-strong hover:bg-surface-sunken",
  ghost:
    "bg-transparent text-muted border border-transparent hover:bg-surface-sunken hover:text-foreground",
  danger: "bg-critical text-white hover:opacity-90 border border-transparent",
};

const SIZES: Record<Size, string> = {
  sm: "h-7 px-2 text-xs gap-1.5",
  // 36px: comfortably above the 24px minimum in WCAG 2.2 target size (2.5.8),
  // and close to the 44px recommended for touch on the mobile layouts.
  md: "h-9 px-3 text-sm gap-2",
};

const BASE =
  "inline-flex items-center justify-center rounded font-medium transition-colors " +
  "disabled:pointer-events-none disabled:opacity-50 select-none";

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
  size?: Size;
  /** Iconify name rendered before the label. */
  icon?: string;
  children?: ReactNode;
}

export function Button({
  variant = "secondary",
  size = "md",
  icon,
  children,
  className,
  type = "button",
  ...rest
}: ButtonProps) {
  return (
    <button type={type} className={cn(BASE, VARIANTS[variant], SIZES[size], className)} {...rest}>
      {icon && <Icon name={icon} size={size === "sm" ? 14 : 16} />}
      {children}
    </button>
  );
}

export interface IconButtonProps extends Omit<ButtonProps, "children" | "icon"> {
  icon: string;
  /** Required: this is the button's only accessible name. */
  label: string;
}

export function IconButton({
  icon,
  label,
  variant = "ghost",
  size = "md",
  className,
  ...rest
}: IconButtonProps) {
  return (
    <button
      type="button"
      aria-label={label}
      // A visible tooltip for sighted users; `aria-label` covers the rest.
      title={label}
      className={cn(
        BASE,
        VARIANTS[variant],
        size === "sm" ? "size-7" : "size-9",
        "px-0",
        className,
      )}
      {...rest}
    >
      <Icon name={icon} size={size === "sm" ? 15 : 18} />
    </button>
  );
}

export function ButtonLink({
  href,
  variant = "secondary",
  size = "md",
  icon,
  children,
  className,
}: {
  href: string;
  variant?: Variant;
  size?: Size;
  icon?: string;
  children: ReactNode;
  className?: string;
}) {
  return (
    <Link
      href={href}
      className={cn(BASE, VARIANTS[variant], SIZES[size], "no-underline", className)}
    >
      {icon && <Icon name={icon} size={size === "sm" ? 14 : 16} />}
      {children}
    </Link>
  );
}
