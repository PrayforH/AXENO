type ObservabilityEnvironment = Record<string, string | undefined>;

export function buildLangfuseTraceListUrl(
  environment: ObservabilityEnvironment,
  runId?: string,
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

  const target = new URL(
    `/project/${encodeURIComponent(projectId)}/traces`,
    `${base.origin}/`,
  );
  if (runId?.trim()) target.searchParams.set("search", runId.trim());
  return target;
}
