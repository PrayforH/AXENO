import { proxyAguiRequest } from "../../../../lib/harness-proxy";
import { getHarnessServerConfig } from "../../../../lib/server-config";

export const dynamic = "force-dynamic";

export async function POST(
  request: Request,
  context: { params: Promise<{ path: string[] }> },
) {
  const { path } = await context.params;
  return proxyAguiRequest(
    request,
    getHarnessServerConfig(),
    fetch,
    path.map(encodeURIComponent).join("/"),
  );
}
