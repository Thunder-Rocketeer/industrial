import { env } from "@/lib/env";

/**
 * Placeholder root route.
 *
 * The authenticated application shell and the executive dashboard are built in
 * later phases. This page exists so the development server has something to
 * render and so the Phase 1 foundations can be verified end to end.
 */
export default function Home() {
  return (
    <div className="flex flex-1 items-center justify-center bg-zinc-50 px-6 py-16 dark:bg-zinc-950">
      <main id="main-content" className="w-full max-w-xl">
        <p className="text-xs font-medium tracking-widest text-zinc-500 uppercase dark:text-zinc-400">
          Phase 1 — foundations
        </p>
        <h1 className="mt-3 text-3xl font-semibold tracking-tight text-zinc-900 dark:text-zinc-50">
          {env.NEXT_PUBLIC_APP_NAME}
        </h1>
        <p className="mt-4 text-sm leading-relaxed text-zinc-600 dark:text-zinc-400">
          Project scaffolding is in place. The application shell, authentication and dashboard
          modules are implemented in the phases that follow.
        </p>
        <dl className="mt-8 grid grid-cols-1 gap-px overflow-hidden rounded-lg border border-zinc-200 bg-zinc-200 text-sm sm:grid-cols-2 dark:border-zinc-800 dark:bg-zinc-800">
          <div className="bg-white p-4 dark:bg-zinc-900">
            <dt className="text-zinc-500 dark:text-zinc-400">Environment</dt>
            <dd className="mt-1 font-medium text-zinc-900 dark:text-zinc-50">
              {env.NEXT_PUBLIC_APP_ENV}
            </dd>
          </div>
          <div className="bg-white p-4 dark:bg-zinc-900">
            <dt className="text-zinc-500 dark:text-zinc-400">API base URL</dt>
            <dd className="mt-1 font-mono text-xs break-all text-zinc-900 dark:text-zinc-50">
              {env.NEXT_PUBLIC_API_BASE_URL}
            </dd>
          </div>
        </dl>
      </main>
    </div>
  );
}
