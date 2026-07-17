type ObservabilityEnvironment = Record<string, string | undefined>;

export function buildLangfuseTraceListUrl(
  environment: ObservabilityEnvironment,
  runId?: string,
  traceId?: string,
): URL | undefined {
  const rawBase = environment.LANGFUSE_BASE_URL?.trim();
  const projectId = environment.LANGFUSE_PROJECT_ID?.trim();
  if (!rawBase || !projectId || !/^[A-Za-z0-9_-]+$/.test(projectId)) return undefined;

  let base: URL;
  try {
    base = new URL(rawBase);
  } catch {
    return undefined;
  }
  if (base.protocol !== "http:" && base.protocol !== "https:") return undefined;

  const normalizedTraceId = traceId?.trim();
  const tracePath =
    normalizedTraceId && /^[a-fA-F0-9]{32}$/.test(normalizedTraceId)
      ? `/project/${encodeURIComponent(projectId)}/traces/${normalizedTraceId.toLowerCase()}`
      : `/project/${encodeURIComponent(projectId)}/traces`;
  const target = new URL(tracePath, `${base.origin}/`);
  if (!normalizedTraceId?.match(/^[a-fA-F0-9]{32}$/) && runId?.trim()) {
    target.searchParams.set("search", runId.trim());
  }
  return target;
}
