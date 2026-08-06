import { proxyAgentCatalogRequest } from "../../../../lib/harness-proxy";
import { getHarnessServerConfig } from "../../../../lib/server-config";

export const dynamic = "force-dynamic";

export async function GET(request: Request): Promise<Response> {
  return proxyAgentCatalogRequest(request, getHarnessServerConfig());
}
