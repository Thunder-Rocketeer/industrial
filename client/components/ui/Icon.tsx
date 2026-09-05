import { Icon as IconifyIcon, type IconProps as IconifyIconProps } from "@iconify/react";

/**
 * The application's only icon component.
 *
 * Spec section 20: use Iconify consistently and do not mix icon libraries.
 * Routing every icon through this wrapper makes that rule enforceable and gives
 * one place to change sizing or set defaults later.
 *
 * Accessibility (spec section 19): an icon is decorative by default and is
 * hidden from assistive technology. Pass `label` only when the icon is the sole
 * carrier of meaning — and prefer adding visible text instead, since spec
 * section 45 forbids conveying state through an icon or colour alone.
 */
export interface IconProps extends Omit<IconifyIconProps, "icon" | "aria-hidden"> {
  /** Iconify icon name, for example `"mdi:factory"`. */
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
