"use client";

import { RequireAuth } from "@/components/layout/RequireAuth";
import { Icon } from "@/components/ui/Icon";
import { useAuth } from "@/providers/auth-provider";

/**
 * Placeholder root route, now behind authentication.
 *
 * The dashboard itself is Phase 5. This exists so the authentication
 * foundation can be exercised end to end: sign in, see the session, sign out.
 */
function SignedInHome() {
  const { user, signOut } = useAuth();

  return (
    <div className="flex flex-1 items-center justify-center bg-zinc-50 px-6 py-16 dark:bg-zinc-950">
      <main id="main-content" className="w-full max-w-xl">
        <p className="text-xs font-medium tracking-widest text-zinc-500 uppercase dark:text-zinc-400">
          Phase 4 — authentication
        </p>
        <h1 className="mt-3 text-3xl font-semibold tracking-tight text-zinc-900 dark:text-zinc-50">
          Signed in
        </h1>
        <p className="mt-4 text-sm leading-relaxed text-zinc-600 dark:text-zinc-400">
          Authentication is working. The dashboard modules are built in the phases that follow.
        </p>

        <dl className="mt-8 grid grid-cols-1 gap-px overflow-hidden rounded-lg border border-zinc-200 bg-zinc-200 text-sm sm:grid-cols-2 dark:border-zinc-800 dark:bg-zinc-800">
          <div className="bg-white p-4 dark:bg-zinc-900">
            <dt className="text-zinc-500 dark:text-zinc-400">Name</dt>
            <dd className="mt-1 font-medium text-zinc-900 dark:text-zinc-50">{user?.name}</dd>
          </div>
          <div className="bg-white p-4 dark:bg-zinc-900">
            <dt className="text-zinc-500 dark:text-zinc-400">Email</dt>
            <dd className="mt-1 font-medium break-all text-zinc-900 dark:text-zinc-50">
              {user?.email}
            </dd>
          </div>
          <div className="bg-white p-4 dark:bg-zinc-900">
            <dt className="text-zinc-500 dark:text-zinc-400">Role</dt>
            {/* The label, not the code: state must be readable as text. */}
            <dd className="mt-1 font-medium text-zinc-900 dark:text-zinc-50">{user?.role_label}</dd>
          </div>
          <div className="bg-white p-4 dark:bg-zinc-900">
            <dt className="text-zinc-500 dark:text-zinc-400">Permissions</dt>
            <dd className="mt-1 font-medium text-zinc-900 dark:text-zinc-50">
              {user?.permissions.length ?? 0}
            </dd>
          </div>
        </dl>

        <button
          type="button"
          onClick={() => void signOut()}
          className="mt-8 inline-flex items-center gap-2 rounded border border-zinc-300 bg-white px-4 py-2 text-sm font-medium text-zinc-900 transition hover:bg-zinc-50 focus:outline focus:outline-2 focus:outline-offset-2 focus:outline-blue-600 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-50 dark:hover:bg-zinc-800"
        >
          <Icon name="mdi:logout" size={16} />
          Sign out
        </button>
      </main>
    </div>
  );
}

export default function Home() {
  return (
    <RequireAuth>
      <SignedInHome />
    </RequireAuth>
  );
}
