import { getHarnessServerConfig } from "../../../../lib/server-config";

export const dynamic = "force-dynamic";

export async function GET(): Promise<Response> {
  const config = getHarnessServerConfig();
  const upstream = await fetch(`${config.apiUrl}/v1/auth/config`, {
    cache: "no-store",
  });
  if (!upstream.ok) {
    return new Response(upstream.body, {
      status: upstream.status,
      headers: { "Content-Type": "application/json" },
    });
  }
  const payload = (await upstream.json()) as {
    registration_enabled: boolean;
    providers: { google: boolean; github: boolean };
  };
  payload.providers.google = payload.providers.google && Boolean(config.googleClientId);
  payload.providers.github = payload.providers.github && Boolean(config.githubClientId);
  return Response.json(payload);
}
