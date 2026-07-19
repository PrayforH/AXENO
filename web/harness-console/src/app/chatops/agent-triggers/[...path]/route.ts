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
    "chatops/agent-triggers",
    fetch,
    path.map(encodeURIComponent).join("/"),
  );
}

export const POST = proxy;
