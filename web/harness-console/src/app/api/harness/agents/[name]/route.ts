import { proxyToHarness } from "../../../../../lib/harness-api-proxy";

export const dynamic = "force-dynamic";

export async function GET(
  request: Request,
  { params }: { params: Promise<{ name: string }> },
) {
  const { name } = await params;
  return proxyToHarness(request, `/v1/agents/${encodeURIComponent(name)}`);
}
