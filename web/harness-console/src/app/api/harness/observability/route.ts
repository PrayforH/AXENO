import { buildLangfuseTraceListUrl } from "../../../../lib/observability-link";

export async function GET(request: Request): Promise<Response> {
  const runId = new URL(request.url).searchParams.get("run_id") ?? undefined;
  const target = buildLangfuseTraceListUrl(process.env, runId);
  if (!target) {
    return Response.json(
      { error: "External observability is not configured" },
      { status: 404 },
    );
  }
  return Response.redirect(target, 307);
}
