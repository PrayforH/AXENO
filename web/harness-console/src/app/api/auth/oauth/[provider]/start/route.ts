import { createHash, randomBytes } from "node:crypto";
import { getHarnessServerConfig } from "../../../../../../lib/server-config";

type Provider = "google" | "github";

function cookie(name: string, value: string, secure: boolean, maxAge = 600): string {
  return [
    `${name}=${encodeURIComponent(value)}`,
    "Path=/api/auth/oauth",
    "HttpOnly",
    "SameSite=Lax",
    `Max-Age=${maxAge}`,
    secure ? "Secure" : "",
  ]
    .filter(Boolean)
    .join("; ");
}

function safeReturnTo(value: string | null): string {
  return value?.startsWith("/") && !value.startsWith("//") ? value : "/";
}

export async function GET(
  request: Request,
  context: { params: Promise<{ provider: string }> },
): Promise<Response> {
  const { provider: rawProvider } = await context.params;
  if (rawProvider !== "google" && rawProvider !== "github") {
    return Response.json({ error: "unsupported provider" }, { status: 404 });
  }
  const provider: Provider = rawProvider;
  const config = getHarnessServerConfig();
  const clientId =
    provider === "google" ? config.googleClientId : config.githubClientId;
  if (!clientId) {
    return Response.redirect(new URL("/login?error=sso_unavailable", request.url));
  }
  const state = randomBytes(32).toString("base64url");
  const verifier = randomBytes(64).toString("base64url");
  const challenge = createHash("sha256").update(verifier).digest("base64url");
  const origin = config.publicUrl || new URL(request.url).origin;
  const redirectUri = `${origin}/api/auth/oauth/${provider}/callback`;
  const authorizationUrl = new URL(
    provider === "google"
      ? "https://accounts.google.com/o/oauth2/v2/auth"
      : "https://github.com/login/oauth/authorize",
  );
  authorizationUrl.searchParams.set("client_id", clientId);
  authorizationUrl.searchParams.set("redirect_uri", redirectUri);
  authorizationUrl.searchParams.set("response_type", "code");
  authorizationUrl.searchParams.set("scope", provider === "google" ? "openid email profile" : "read:user user:email");
  authorizationUrl.searchParams.set("state", state);
  authorizationUrl.searchParams.set("code_challenge", challenge);
  authorizationUrl.searchParams.set("code_challenge_method", "S256");
  if (provider === "google") authorizationUrl.searchParams.set("access_type", "online");

  const headers = new Headers({ Location: authorizationUrl.toString() });
  headers.append("Set-Cookie", cookie("harness_oauth_state", state, config.cookieSecure));
  headers.append("Set-Cookie", cookie("harness_oauth_verifier", verifier, config.cookieSecure));
  headers.append("Set-Cookie", cookie("harness_oauth_provider", provider, config.cookieSecure));
  headers.append(
    "Set-Cookie",
    cookie(
      "harness_oauth_return_to",
      safeReturnTo(new URL(request.url).searchParams.get("return_to")),
      config.cookieSecure,
    ),
  );
  return new Response(null, { status: 302, headers });
}
