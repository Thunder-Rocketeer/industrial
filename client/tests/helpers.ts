/**
 * Shared test fixtures.
 *
 * Deliberately small. Each test file builds its own provider wrapper, because
 * the wrappers differ meaningfully -- some need the auth provider, some only a
 * QueryClient -- and a single "render with everything" helper hides which
 * dependency a test is actually exercising.
 */
import type { CurrentUser } from "@/types/auth";

/** A signed-in user holding every read permission. */
export const TEST_USER: CurrentUser = {
  id: "00000000-0000-4000-8000-000000000001",
  email: "manager@factory.test",
  name: "Priya Raman",
  role: "FACTORY_MANAGER",
  role_label: "Factory Manager",
  avatar_url: null,
  is_active: true,
  last_login_at: "2026-01-15T06:00:00Z",
  permissions: [
    "dashboard:read",
    "production:read",
    "quality:read",
    "inventory:read",
    "machines:read",
    "analytics:read",
    "alerts:read",
    "maintenance:read",
  ],
};
