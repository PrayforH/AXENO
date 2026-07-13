import { downloadArtifact } from "../../../../../lib/harness-server";

const FORWARDED_HEADERS = [
  "Content-Type",
  "Content-Length",
  "Content-Disposition",
] as const;

export async function GET(
  request: Request,
  context: { params: Promise<{ artifactId: string }> },
): Promise<Response> {
  const { artifactId } = await context.params;
  const upstream = await downloadArtifact(artifactId);
  const headers = new Headers();
  for (const name of FORWARDED_HEADERS) {
    const value = upstream.headers.get(name);
    if (value) headers.set(name, value);
  }
  if (new URL(request.url).searchParams.get("preview") === "1") {
    headers.set("Content-Disposition", "inline");
  }
  return new Response(upstream.body, { status: upstream.status, headers });
}
