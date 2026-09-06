"use client";

/**
 * An accessible slide-over panel (spec sections 1 and 18).
 *
 * Written by hand rather than pulled from a dialog library, because the four
 * things a modal must do are small and are exactly the four things that get
 * skipped:
 *
 *   1. **Escape closes it.** Expected, and the only exit for a keyboard user
 *      who cannot reach the close button.
 *   2. **Focus moves in and comes back.** On open, focus lands inside; on
 *      close, it returns to the control that opened it. Without the return, a
 *      keyboard user is dropped at the top of the document every time.
 *   3. **Tab is trapped.** Otherwise Tab walks out of the drawer into page
 *      content that is visually behind an overlay -- focus lands somewhere the
 *      user cannot see.
 *   4. **The page behind does not scroll.** On mobile a scrolling background
 *      under an open drawer is disorienting.
 *
 * `role="dialog"` with `aria-modal` and a labelled title tells assistive
 * technology the rest of the page is inert while it is open.
 */
import { useCallback, useEffect, useId, useRef, type ReactNode } from "react";

import { IconButton } from "@/components/ui/Button";

const FOCUSABLE =
  'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

export function Drawer({
  open,
  onClose,
  title,
  children,
  side = "left",
}: {
  open: boolean;
  onClose: () => void;
  title: string;
  children: ReactNode;
  side?: "left" | "right";
}) {
  const panelRef = useRef<HTMLDivElement>(null);
  const restoreFocusRef = useRef<HTMLElement | null>(null);
  const titleId = useId();

  const handleKeyDown = useCallback(
    (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        onClose();
        return;
      }
      if (event.key !== "Tab" || !panelRef.current) {
        return;
      }

      const focusable = Array.from(
        panelRef.current.querySelectorAll<HTMLElement>(FOCUSABLE),
      ).filter((element) => element.offsetParent !== null);
      if (focusable.length === 0) {
        return;
      }

      const first = focusable[0];
      const last = focusable[focusable.length - 1];

      // Wrap at both ends, so Tab and Shift+Tab cycle within the panel.
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    },
    [onClose],
  );

  useEffect(() => {
    if (!open) {
      return;
    }

    restoreFocusRef.current = document.activeElement as HTMLElement | null;

    const { overflow } = document.body.style;
    document.body.style.overflow = "hidden";
    document.addEventListener("keydown", handleKeyDown);

    // Focus the panel itself rather than its first link: a screen reader then
    // announces the dialog's title before its contents.
    panelRef.current?.focus();

    return () => {
      document.body.style.overflow = overflow;
      document.removeEventListener("keydown", handleKeyDown);
      restoreFocusRef.current?.focus?.();
    };
  }, [open, handleKeyDown]);

  if (!open) {
    return null;
  }

  return (
    <div className="fixed inset-0 z-50 lg:hidden">
      {/* Decorative scrim. The dialog is dismissible by Escape and by the close
          button, so this click target is a convenience, not the only exit. */}
      <div className="absolute inset-0 bg-black/40" onClick={onClose} aria-hidden="true" />
      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        tabIndex={-1}
        className={`bg-surface border-border-base absolute inset-y-0 flex w-[17rem] max-w-[85vw] flex-col ${
          side === "left" ? "left-0 border-r" : "right-0 border-l"
        }`}
      >
        <div className="border-border-base flex items-center justify-between border-b px-4 py-3">
          <h2 id={titleId} className="text-foreground text-sm font-semibold">
            {title}
          </h2>
          <IconButton icon="mdi:close" label="Close menu" size="sm" onClick={onClose} />
        </div>
        <div className="flex min-h-0 flex-1 flex-col overflow-y-auto">{children}</div>
      </div>
    </div>
  );
}
