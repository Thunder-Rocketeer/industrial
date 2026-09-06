/**
 * Display formatting.
 *
 * Presentation only: every function here takes a value the backend already
 * computed and returns a string. None of them derive a value from another.
 *
 * A fixed locale is used rather than the browser's. Next.js renders on the
 * server first, and `toLocaleString()` with the runtime default produces
 * "1,234" on the server and "1.234" in a browser set to German -- React then
 * reports a hydration mismatch and re-renders the subtree. Pinning the locale
 * makes both sides agree. If the dashboard is ever localized, this constant is
 * the place that changes.
 */

const LOCALE = "en-US";

/** Value shown where the backend sent null. */
export const EMPTY_VALUE = "—"; // em dash

const numberFormat = new Intl.NumberFormat(LOCALE);
const currencyFormat = new Intl.NumberFormat(LOCALE, {
  style: "currency",
  currency: "USD",
  maximumFractionDigits: 0,
});
const dateFormat = new Intl.DateTimeFormat(LOCALE, {
  day: "2-digit",
  month: "short",
  year: "numeric",
  timeZone: "UTC",
});
const dateTimeFormat = new Intl.DateTimeFormat(LOCALE, {
  day: "2-digit",
  month: "short",
  year: "numeric",
  hour: "2-digit",
  minute: "2-digit",
  hour12: false,
  timeZone: "UTC",
});

/** Thousands-separated integer. */
export function formatNumber(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return EMPTY_VALUE;
  }
  return numberFormat.format(value);
}

/**
 * A percentage the backend calculated.
 *
 * The value arrives as a percentage already (92.4, not 0.924), so this only
 * rounds and appends the sign. It never divides.
 */
export function formatPercentage(value: number | null | undefined, fractionDigits = 1): string {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return EMPTY_VALUE;
  }
  return `${value.toFixed(fractionDigits)}%`;
}

/**
 * An ISO date (`YYYY-MM-DD`).
 *
 * Parsed field by field rather than through `new Date(string)`. The string form
 * is interpreted as UTC midnight, so in any timezone behind UTC a shift date of
 * 2026-01-05 renders as 4 Jan -- an off-by-one on every date in the table for
 * users in the Americas.
 */
export function formatDate(value: string | null | undefined): string {
  if (!value) {
    return EMPTY_VALUE;
  }
  const [year, month, day] = value.slice(0, 10).split("-").map(Number);
  if (!year || !month || !day) {
    return EMPTY_VALUE;
  }
  return dateFormat.format(new Date(Date.UTC(year, month - 1, day)));
}

/**
 * An ISO timestamp.
 *
 * Rendered in UTC, matching the backend, which stores and returns everything in
 * UTC (spec section 41). Two people in different offices comparing a shift
 * start time need to be reading the same clock.
 */
export function formatDateTime(value: string | null | undefined): string {
  if (!value) {
    return EMPTY_VALUE;
  }
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) {
    return EMPTY_VALUE;
  }
  return `${dateTimeFormat.format(parsed)} UTC`;
}

/** A duration in minutes, as hours and minutes past an hour. */
export function formatMinutes(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return EMPTY_VALUE;
  }
  if (value < 60) {
    return `${Math.round(value)} min`;
  }
  const hours = Math.floor(value / 60);
  const minutes = Math.round(value % 60);
  return minutes === 0 ? `${hours} h` : `${hours} h ${minutes} min`;
}

/** A monetary amount. */
export function formatCurrency(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return EMPTY_VALUE;
  }
  return currencyFormat.format(value);
}

/** A string that may be null. */
export function formatText(value: string | null | undefined): string {
  const trimmed = value?.trim();
  return trimmed ? trimmed : EMPTY_VALUE;
}

/** A quantity with its unit of measure. */
export function formatQuantity(
  value: number | null | undefined,
  unit: string | null | undefined,
): string {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return EMPTY_VALUE;
  }
  return unit ? `${numberFormat.format(value)} ${unit}` : numberFormat.format(value);
}

/**
 * A count of days relative to today, as text.
 *
 * Used for maintenance due dates, where the backend sends a signed number of
 * days and negative means overdue.
 */
export function formatRelativeDays(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return EMPTY_VALUE;
  }
  const days = Math.round(value);
  if (days === 0) {
    return "Today";
  }
  if (days < 0) {
    const overdue = Math.abs(days);
    return `${overdue} ${overdue === 1 ? "day" : "days"} overdue`;
  }
  return `In ${days} ${days === 1 ? "day" : "days"}`;
}
