import type { HarnessServerConfig } from "./server-config";

export const ACCESS_COOKIE = "harness_access_token";
export const REFRESH_COOKIE = "harness_refresh_token";

export type AuthUser = {
  user_id: string;
  email: string;
  display_name: string;
  email_verified: boolean;
};

export type Membership = {
  tenant_id: string;
  user_id: string;
  role: "owner" | "admin" | "member" | "viewer";
};

export type AuthSessionPayload = {
  access_token: string;
  refresh_token: string;
  token_type: "bearer";
  expires_in: number;
  user: AuthUser;
  membership: Membership;
};

export function readCookie(request: Request, name: string): string | undefined {
  const cookie = request.headers.get("cookie") ?? "";
  for (const segment of cookie.split(";")) {
    const [key, ...parts] = segment.trim().split("=");
    if (key === name) return decodeURIComponent(parts.join("="));
  }
  return undefined;
}

function serializeCookie(
  name: string,
  value: string,
  maxAge: number,
  secure: boolean,
): string {
  return [
    `${name}=${encodeURIComponent(value)}`,
    "Path=/",
    "HttpOnly",
    "SameSite=Lax",
    `Max-Age=${Math.max(0, Math.floor(maxAge))}`,
    secure ? "Secure" : "",
  ]
    .filter(Boolean)
    .join("; ");
}

export function appendSessionCookies(
  headers: Headers,
  session: AuthSessionPayload,
  config: HarnessServerConfig,
): void {
  headers.append(
    "Set-Cookie",
    serializeCookie(
      ACCESS_COOKIE,
      session.access_token,
      session.expires_in,
      config.cookieSecure,
    ),
  );
  headers.append(
    "Set-Cookie",
    serializeCookie(
      REFRESH_COOKIE,
      session.refresh_token,
      config.refreshCookieDays * 86400,
      config.cookieSecure,
    ),
  );
}

export function appendClearedSessionCookies(
  headers: Headers,
  config: HarnessServerConfig,
): void {
  headers.append(
    "Set-Cookie",
    serializeCookie(ACCESS_COOKIE, "", 0, config.cookieSecure),
  );
  headers.append(
    "Set-Cookie",
    serializeCookie(REFRESH_COOKIE, "", 0, config.cookieSecure),
  );
}

export async function refreshSession(
  request: Request,
  config: HarnessServerConfig,
  fetcher: typeof fetch = fetch,
): Promise<AuthSessionPayload | undefined> {
  const refreshToken = readCookie(request, REFRESH_COOKIE);
  if (!refreshToken) return undefined;
  const response = await fetcher(`${config.apiUrl}/v1/auth/refresh`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ refresh_token: refreshToken }),
    cache: "no-store",
  });
  if (!response.ok) return undefined;
  return (await response.json()) as AuthSessionPayload;
}
