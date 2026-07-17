import { getHarnessServerConfig } from "../../../../lib/server-config";

export const dynamic = "force-dynamic";

export async function GET(): Promise<Response> {
  const config = getHarnessServerConfig();
  return Response.json({
    name: config.agentName,
    version: config.agentVersion,
  });
}
