import { proxyExternalAgentRequest } from "../../../../lib/harness-proxy";
import { getHarnessServerConfig } from "../../../../lib/server-config";

export const dynamic = "force-dynamic";

async function proxy(
  request: Request,
  context: { params: Promise<{ path: string[] }> },
) {
  const { path } = await context.params;
  return proxyExternalAgentRequest(
    request,
    getHarnessServerConfig(),
    "a2a/agent-triggers",
    fetch,
    path.map(encodeURIComponent).join("/"),
  );
}

export const GET = proxy;
export const POST = proxy;
