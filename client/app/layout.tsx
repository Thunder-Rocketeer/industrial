import type { Metadata, Viewport } from "next";

import { AppProviders } from "@/providers/app-providers";
import { env } from "@/lib/env";

import "./globals.css";

export const metadata: Metadata = {
  title: {
    default: env.NEXT_PUBLIC_APP_NAME,
    template: `%s | ${env.NEXT_PUBLIC_APP_NAME}`,
  },
  description:
    "Production, quality, inventory and machine monitoring for an automobile component factory.",
  // The dashboard is behind authentication and holds operational data.
  robots: { index: false, follow: false },
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  // Spec section 19: never block zoom; users must be able to scale the UI.
  maximumScale: 5,
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en" className="h-full antialiased">
      <body className="flex min-h-full flex-col">
        {/* Spec section 19: keyboard users must be able to bypass the nav. */}
        <a
          href="#main-content"
          className="sr-only focus:not-sr-only focus:absolute focus:top-4 focus:left-4 focus:z-50 focus:rounded focus:bg-white focus:px-4 focus:py-2 focus:text-sm focus:font-medium focus:text-zinc-900 focus:shadow focus:outline focus:outline-2 focus:outline-offset-2 focus:outline-blue-600 dark:focus:bg-zinc-900 dark:focus:text-zinc-50"
        >
          Skip to main content
        </a>
        <AppProviders>{children}</AppProviders>
      </body>
    </html>
  );
}
