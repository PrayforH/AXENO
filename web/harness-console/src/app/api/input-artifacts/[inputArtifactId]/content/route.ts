import { downloadInputArtifact } from "../../../../../lib/harness-server";

const FORWARDED_HEADERS = [
  "Content-Type",
  "Content-Length",
  "Content-Disposition",
] as const;

export async function GET(
  request: Request,
  context: { params: Promise<{ inputArtifactId: string }> },
): Promise<Response> {
  const { inputArtifactId } = await context.params;
  const upstream = await downloadInputArtifact(inputArtifactId, request);
  const headers = new Headers();
  for (const name of FORWARDED_HEADERS) {
    const value = upstream.headers.get(name);
    if (value) headers.set(name, value);
  }
  const setCookie = upstream.headers.get("set-cookie");
  if (setCookie) headers.set("Set-Cookie", setCookie);
  return new Response(upstream.body, { status: upstream.status, headers });
}
