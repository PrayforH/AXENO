import { proxyTeamSpaceRequest } from "../../../lib/harness-proxy";
import { getHarnessServerConfig } from "../../../lib/server-config";

export const dynamic = "force-dynamic";

export function GET(request: Request) {
  return proxyTeamSpaceRequest(request, getHarnessServerConfig());
}

export function POST(request: Request) {
  return proxyTeamSpaceRequest(request, getHarnessServerConfig());
}
