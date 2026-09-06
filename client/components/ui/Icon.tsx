import { Icon as IconifyIcon, addIcon, type IconProps as IconifyIconProps } from "@iconify/react";

import { BUNDLED_ICONS } from "@/lib/icons.generated";

/**
 * The application's only icon component.
 *
 * Spec section 33: use Iconify consistently and do not mix icon libraries.
 * Routing every icon through this wrapper makes that rule enforceable and gives
 * one place to change sizing or set defaults later.
 *
 * OFFLINE BY DESIGN
 *
 * `@iconify/react` normally resolves an unknown icon name by fetching it from
 * `api.iconify.design`. Every icon used here is instead registered into its
 * local store at module load from `lib/icons.generated.ts`, so no request is
 * ever made. Three reasons, in order of weight:
 *
 *   1. A factory network may be segmented or offline. Icons that silently fail
 *      to render take the status indicators with them.
 *   2. The Content-Security-Policy would otherwise need `connect-src` opened to
 *      three public CDN hosts — a real widening, for decoration.
 *   3. Per-view icon requests would tell a third party which pages are used.
 *
 * Run `node scripts/generate-icons.mjs` after adding a new icon name.
 *
 * ACCESSIBILITY (spec sections 18 and 33)
 *
 * An icon is decorative by default and hidden from assistive technology. Pass
 * `label` only when the icon is the sole carrier of meaning — and prefer adding
 * visible text instead, since spec section 32 forbids conveying state through
 * an icon or colour alone.
 */

/*
 * Registered at module load, before any icon renders.
 *
 * `addIcon` is idempotent, and this module is evaluated once per bundle, so the
 * cost is paid a single time.
 */
for (const [name, data] of Object.entries(BUNDLED_ICONS)) {
  addIcon(name, data);
}

export interface IconProps extends Omit<IconifyIconProps, "icon" | "aria-hidden"> {
  /** Iconify icon name, for example `"mdi:factory"`. Must be in the registry. */
  name: string;
  /** CSS size applied to both width and height. Defaults to `1em`. */
  size?: string | number;
  /** Accessible name. Omit for decorative icons accompanied by visible text. */
  label?: string;
}

export function Icon({ name, size = "1em", label, ...rest }: IconProps) {
  const isDecorative = label === undefined;

  return (
    <IconifyIcon
      icon={name}
      width={size}
      height={size}
      role={isDecorative ? undefined : "img"}
      aria-hidden={isDecorative || undefined}
      aria-label={label}
      {...rest}
    />
  );
}
