import {
  type AuthSessionPayload,
  appendSessionCookies,
  readCookie,
} from "../../../../../../lib/auth-session";
import { getHarnessServerConfig } from "../../../../../../lib/server-config";

function clearOAuthCookie(name: string, secure: boolean): string {
  return [
    `${name}=`,
    "Path=/api/auth/oauth",
    "HttpOnly",
    "SameSite=Lax",
    "Max-Age=0",
    secure ? "Secure" : "",
  ]
    .filter(Boolean)
    .join("; ");
}

export async function GET(
  request: Request,
  context: { params: Promise<{ provider: string }> },
): Promise<Response> {
  const { provider } = await context.params;
  const url = new URL(request.url);
  const config = getHarnessServerConfig();
  const expectedState = readCookie(request, "harness_oauth_state");
  const verifier = readCookie(request, "harness_oauth_verifier");
  const expectedProvider = readCookie(request, "harness_oauth_provider");
  const returnTo = readCookie(request, "harness_oauth_return_to") || "/";
  const code = url.searchParams.get("code");
  const state = url.searchParams.get("state");
  const validProvider = provider === "google" || provider === "github";
  if (
    !validProvider ||
    !code ||
    !state ||
    !expectedState ||
    state !== expectedState ||
    expectedProvider !== provider ||
    !verifier
  ) {
    return Response.redirect(new URL("/login?error=sso_state_invalid", request.url));
  }
  const origin = config.publicUrl || url.origin;
  const redirectUri = `${origin}/api/auth/oauth/${provider}/callback`;
  const upstream = await fetch(`${config.apiUrl}/v1/auth/oauth/${provider}/exchange`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ code, redirect_uri: redirectUri, code_verifier: verifier }),
    cache: "no-store",
  });
  if (!upstream.ok) {
    return Response.redirect(new URL("/login?error=sso_exchange_failed", request.url));
  }
  const session = (await upstream.json()) as AuthSessionPayload;
  const headers = new Headers({ Location: new URL(returnTo, origin).toString() });
  appendSessionCookies(headers, session, config);
  for (const name of [
    "harness_oauth_state",
    "harness_oauth_verifier",
    "harness_oauth_provider",
    "harness_oauth_return_to",
  ]) {
    headers.append("Set-Cookie", clearOAuthCookie(name, config.cookieSecure));
  }
  return new Response(null, { status: 302, headers });
}
