"use client";

/**
 * Reusable filter controls (spec section 27).
 *
 * Every control here is a native `<select>` or `<input>`. That is a deliberate
 * choice over a custom combobox: native controls are keyboard accessible,
 * screen-reader correct, and usable on a touchscreen for free, and a hand-rolled
 * listbox gets all three subtly wrong. On a factory tablet the native picker is
 * also the better interaction.
 *
 * Two behaviours prevent the request storms spec section 27 warns about:
 *
 *  - Selects commit on `change`, which fires once per choice.
 *  - The text search debounces, so typing "brake disc" issues one request
 *    rather than ten.
 *
 * Every control has a real `<label>`. A placeholder is not a label: it vanishes
 * on focus and is never announced as one (WCAG 3.3.2).
 */
import { useEffect, useId, useState } from "react";

import { Button } from "@/components/ui/Button";
import { Icon } from "@/components/ui/Icon";
import { cn } from "@/lib/utils/cn";

const CONTROL =
  "border-border-strong bg-surface text-foreground h-9 w-full rounded border px-2 text-sm " +
  "disabled:opacity-60";

export interface FilterOption {
  value: string;
  label: string;
}

/** A labelled `<select>`. The empty option means "no filter". */
export function SelectFilter({
  label,
  value,
  options,
  onChange,
  allLabel = "All",
  disabled = false,
  loading = false,
}: {
  label: string;
  value: string | undefined;
  options: FilterOption[];
  onChange: (value: string | undefined) => void;
  allLabel?: string;
  disabled?: boolean;
  loading?: boolean;
}) {
  const id = useId();

  return (
    <div className="min-w-0 flex-1 sm:max-w-52">
      <label htmlFor={id} className="text-subtle mb-1 block text-xs font-medium">
        {label}
      </label>
      <select
        id={id}
        value={value ?? ""}
        disabled={disabled || loading}
        onChange={(event) => onChange(event.target.value || undefined)}
        className={CONTROL}
      >
        <option value="">{loading ? "Loading…" : allLabel}</option>
        {options.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>
    </div>
  );
}

/**
 * Start and end date inputs.
 *
 * `type="date"` gives the platform picker, keyboard entry and locale-aware
 * display, while the value stays a plain `YYYY-MM-DD` — which is exactly what
 * the API wants and what goes in the URL.
 *
 * `max`/`min` cross-bound the two inputs so an end date before its start cannot
 * be chosen. Preventing the invalid state beats reporting it (WCAG 3.3.3).
 */
export function DateRangeFilter({
  startDate,
  endDate,
  onChange,
}: {
  startDate: string | undefined;
  endDate: string | undefined;
  onChange: (range: { start_date?: string; end_date?: string }) => void;
}) {
  const startId = useId();
  const endId = useId();

  return (
    <div className="flex min-w-0 flex-1 gap-2 sm:max-w-80">
      <div className="min-w-0 flex-1">
        <label htmlFor={startId} className="text-subtle mb-1 block text-xs font-medium">
          From
        </label>
        <input
          id={startId}
          type="date"
          value={startDate ?? ""}
          max={endDate}
          onChange={(event) => onChange({ start_date: event.target.value || undefined })}
          className={CONTROL}
        />
      </div>
      <div className="min-w-0 flex-1">
        <label htmlFor={endId} className="text-subtle mb-1 block text-xs font-medium">
          To
        </label>
        <input
          id={endId}
          type="date"
          value={endDate ?? ""}
          min={startDate}
          onChange={(event) => onChange({ end_date: event.target.value || undefined })}
          className={CONTROL}
        />
      </div>
    </div>
  );
}

/**
 * A debounced text input.
 *
 * The local draft is what the user types; the committed value is what the URL
 * and the API see, 350ms after they stop. Without this, a ten-character search
 * term is ten renders, ten URL writes and ten requests — the "uncontrolled API
 * request storm" spec section 27 names.
 */
export function SearchFilter({
  label,
  value,
  onChange,
  placeholder,
  delayMs = 350,
}: {
  label: string;
  value: string | undefined;
  onChange: (value: string | undefined) => void;
  placeholder?: string;
  delayMs?: number;
}) {
  const id = useId();
  const [draft, setDraft] = useState(value ?? "");
  const [lastCommitted, setLastCommitted] = useState(value);

  /*
   * Re-sync when the URL changes underneath us: Back, Forward, or Clear.
   *
   * Adjusted during render rather than in an effect. React's own guidance is
   * that syncing state to a prop in `useEffect` causes a cascading second
   * render -- the input paints with the stale text, then repaints. Comparing
   * against the previous prop here means the correct value is on screen in the
   * first pass. See "You Might Not Need an Effect".
   */
  if (value !== lastCommitted) {
    setLastCommitted(value);
    setDraft(value ?? "");
  }

  useEffect(() => {
    if (draft === (value ?? "")) {
      return;
    }
    const timer = window.setTimeout(() => onChange(draft || undefined), delayMs);
    return () => window.clearTimeout(timer);
    // `onChange` is recreated per render at most call sites; including it would
    // reset the timer on every keystroke and defeat the debounce.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [draft, value, delayMs]);

  return (
    <div className="min-w-0 flex-1 sm:max-w-64">
      <label htmlFor={id} className="text-subtle mb-1 block text-xs font-medium">
        {label}
      </label>
      <div className="relative">
        <Icon
          name="mdi:magnify"
          size={15}
          className="text-subtle pointer-events-none absolute top-1/2 left-2 -translate-y-1/2"
        />
        <input
          id={id}
          type="search"
          value={draft}
          placeholder={placeholder}
          onChange={(event) => setDraft(event.target.value)}
          className={cn(CONTROL, "pl-7")}
        />
      </div>
    </div>
  );
}

/**
 * The container for a page's filters.
 *
 * A `<search>` landmark with a label, so a screen-reader user can jump straight
 * to the controls. "Clear" appears only when something is set — a permanently
 * visible reset that does nothing is noise.
 */
export function FilterBar({
  children,
  onReset,
  activeCount = 0,
}: {
  children: React.ReactNode;
  onReset?: () => void;
  activeCount?: number;
}) {
  return (
    <search
      // The explicit role is redundant in browsers that map <search> natively
      // (Chrome 118+, Safari 17+, Firefox 118+) and necessary in those that do
      // not -- without it the element falls back to `generic` and the landmark
      // disappears for a screen-reader user on an older browser.
      role="search"
      aria-label="Filters"
      className="border-border-base bg-surface mb-4 rounded-md border p-3"
    >
      <div className="flex flex-wrap items-end gap-3">
        {children}
        {onReset && activeCount > 0 && (
          <Button size="sm" variant="ghost" icon="mdi:filter-remove-outline" onClick={onReset}>
            Clear {activeCount === 1 ? "filter" : `${activeCount} filters`}
          </Button>
        )}
      </div>
    </search>
  );
}
