import { proxyToHarness } from "../../../../lib/harness-api-proxy";

export const dynamic = "force-dynamic";

export async function GET(request: Request) {
  const url = new URL(request.url);
  const params = new URLSearchParams();
  const limit = url.searchParams.get("limit");
  const offset = url.searchParams.get("offset");
  const sessionId = url.searchParams.get("session_id");
  const status = url.searchParams.get("status");
  if (limit) params.set("limit", limit);
  if (offset) params.set("offset", offset);
  if (sessionId) params.set("session_id", sessionId);
  if (status) params.set("status", status);
  const qs = params.toString();
  return proxyToHarness(request, `/v1/runs${qs ? `?${qs}` : ""}`);
}
