import type { Metadata } from "next";

import { MachineDetailView } from "./MachineDetailView";

/**
 * `/machines/{machineId}` (spec section 23).
 *
 * A Server Component that awaits the route params and passes the id down. It
 * reads no search params, so it needs no Suspense boundary of its own.
 *
 * The id is passed straight to the API, which validates it as a UUID and
 * authorizes the request. A malformed or unauthorized id produces a 404 or 403
 * that the view renders as an error state -- it is never interpolated into
 * markup or a URL.
 */
export const metadata: Metadata = {
  title: "Machine detail",
  description: "Status, production statistics, OEE and maintenance for one machine.",
};

export default async function MachineDetailPage({
  params,
}: {
  params: Promise<{ machineId: string }>;
}) {
  const { machineId } = await params;
  return <MachineDetailView machineId={machineId} />;
}
