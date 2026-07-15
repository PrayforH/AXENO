import { proxyToHarness } from "../../../../../lib/harness-api-proxy";

export const dynamic = "force-dynamic";

export async function GET(
  request: Request,
  { params }: { params: Promise<{ sessionId: string }> },
) {
  const { sessionId } = await params;
  return proxyToHarness(request, `/v1/sessions/${encodeURIComponent(sessionId)}`);
}

export async function DELETE(
  request: Request,
  { params }: { params: Promise<{ sessionId: string }> },
) {
  const { sessionId } = await params;
  return proxyToHarness(request, `/v1/sessions/${encodeURIComponent(sessionId)}`);
}
