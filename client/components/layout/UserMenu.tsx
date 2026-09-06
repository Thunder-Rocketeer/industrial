"use client";

/**
 * Account menu (spec sections 1 and 30).
 *
 * Shows the name, email, role label and avatar, plus sign out.
 *
 * What it deliberately does **not** show is anything derived from the session
 * token. Every field here comes from `GET /auth/me`; nothing is decoded in the
 * browser, because nothing decodable exists there -- the session is an HttpOnly
 * cookie (spec section 30: "do not expose JWT contents").
 *
 * The role is rendered from `role_label`, the backend's own words, rather than
 * a lookup table here. A second vocabulary in the UI drifts from the API's.
 */
import { useEffect, useRef, useState } from "react";

import { Button } from "@/components/ui/Button";
import { Icon } from "@/components/ui/Icon";
import { cn } from "@/lib/utils/cn";
import { useAuth } from "@/providers/auth-provider";

export function UserMenu() {
  const { user, signOut } = useAuth();
  const [open, setOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (!open) {
      return;
    }

    const onPointerDown = (event: MouseEvent) => {
      if (!containerRef.current?.contains(event.target as Node)) {
        setOpen(false);
      }
    };
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setOpen(false);
        // Return focus to the trigger, or the keyboard user is stranded.
        triggerRef.current?.focus();
      }
    };

    document.addEventListener("mousedown", onPointerDown);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("mousedown", onPointerDown);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [open]);

  if (!user) {
    return null;
  }

  const initials = user.name
    .split(" ")
    .map((part) => part[0])
    .filter(Boolean)
    .slice(0, 2)
    .join("")
    .toUpperCase();

  return (
    <div ref={containerRef} className="relative">
      <button
        ref={triggerRef}
        type="button"
        onClick={() => setOpen((value) => !value)}
        aria-expanded={open}
        aria-haspopup="menu"
        className={cn(
          "flex items-center gap-2 rounded px-1.5 py-1 text-sm transition-colors",
          "hover:bg-surface-sunken",
        )}
      >
        <Avatar url={user.avatar_url} initials={initials} />
        <span className="hidden min-w-0 text-left sm:block">
          <span className="text-foreground block max-w-[10rem] truncate text-xs font-medium">
            {user.name}
          </span>
          <span className="text-subtle block max-w-[10rem] truncate text-[11px]">
            {user.role_label}
          </span>
        </span>
        <Icon name="mdi:chevron-down" size={16} className="text-subtle hidden sm:block" />
        <span className="sr-only">Account menu for {user.name}</span>
      </button>

      {open && (
        <div
          role="menu"
          aria-label="Account"
          className="border-border-base bg-surface-raised absolute right-0 z-40 mt-1.5 w-64 rounded-md border p-1 shadow-lg"
        >
          <div className="border-border-base border-b px-3 py-2.5">
            <p className="text-foreground truncate text-sm font-medium">{user.name}</p>
            <p className="text-subtle truncate text-xs" title={user.email}>
              {user.email}
            </p>
            <p className="text-muted mt-1.5 text-xs">
              Role: <span className="font-medium">{user.role_label}</span>
            </p>
          </div>
          <div className="p-1">
            <Button
              variant="ghost"
              size="sm"
              icon="mdi:logout"
              role="menuitem"
              className="w-full justify-start"
              onClick={() => {
                setOpen(false);
                void signOut();
              }}
            >
              Sign out
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}

function Avatar({ url, initials }: { url: string | null; initials: string }) {
  if (url) {
    /*
     * A plain `<img>`, deliberately.
     *
     * The avatar is served from Google's CDN at a host that varies per account.
     * `next/image` requires every such host to be allow-listed in
     * `next.config.ts` and routes the request through the optimizer -- a server
     * round trip to resize an image that is already 28 pixels wide. The
     * `alt=""` is correct rather than lazy: the user's name is rendered
     * immediately beside it, so describing the photo would repeat it.
     */
    return (
      // eslint-disable-next-line @next/next/no-img-element
      <img
        src={url}
        alt=""
        width={28}
        height={28}
        className="border-border-base size-7 shrink-0 rounded-full border object-cover"
        referrerPolicy="no-referrer"
      />
    );
  }

  return (
    <span
      aria-hidden="true"
      className="bg-surface-sunken text-muted border-border-base flex size-7 shrink-0 items-center justify-center rounded-full border text-[11px] font-semibold"
    >
      {initials || "?"}
    </span>
  );
}
