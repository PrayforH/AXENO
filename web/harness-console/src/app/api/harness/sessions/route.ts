import { proxyToHarness } from "../../../../lib/harness-api-proxy";

export const dynamic = "force-dynamic";

export async function GET(request: Request) {
  const url = new URL(request.url);
  const limit = url.searchParams.get("limit") ?? "50";
  const offset = url.searchParams.get("offset") ?? "0";
  return proxyToHarness(request, `/v1/sessions?limit=${limit}&offset=${offset}`);
}
