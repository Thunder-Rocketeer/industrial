import { redirect } from "next/navigation";

/**
 * The root path.
 *
 * Redirects to the dashboard, which is the application's real entry point.
 * `RequireAuth` on the authenticated layout sends a signed-out visitor on to
 * `/login` from there, so this file needs no session knowledge of its own --
 * and stays a Server Component with no client bundle.
 */
export default function RootPage() {
  redirect("/dashboard");
}
