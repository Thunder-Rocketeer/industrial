/**
 * Join class names, dropping falsy values.
 *
 * Deliberately not `clsx` + `tailwind-merge`: this project has no runtime
 * class-conflict problem to solve, because variants are picked from lookup
 * maps rather than spliced together from overlapping strings. Two dependencies
 * to fix a problem the code does not have is a poor trade.
 */
export function cn(...values: (string | false | null | undefined)[]): string {
  return values.filter(Boolean).join(" ");
}
