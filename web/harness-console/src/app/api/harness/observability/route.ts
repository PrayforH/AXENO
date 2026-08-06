import { buildLangfuseTraceListUrl } from "../../../../lib/observability-link";

export async function GET(request: Request): Promise<Response> {
  const searchParams = new URL(request.url).searchParams;
  const runId = searchParams.get("run_id") ?? undefined;
  const traceId = searchParams.get("trace_id") ?? undefined;
  const target = buildLangfuseTraceListUrl(process.env, runId, traceId);
  if (!target) {
    return Response.json(
      { error: "External observability is not configured" },
      { status: 404 },
    );
  }
  return Response.redirect(target, 307);
}
