const SESSION_EXPIRED_PATH = "/login?error=session_expired";

type RedirectLocation = Pick<Location, "replace">;

export function redirectOnUnauthorized(
  response: Response,
  location: RedirectLocation | undefined =
    typeof window === "undefined" ? undefined : window.location,
): boolean {
  if (response.status !== 401) return false;
  location?.replace(SESSION_EXPIRED_PATH);
  return true;
}

export function requireAuthenticatedResponse(response: Response): Response {
  if (redirectOnUnauthorized(response)) {
    throw new Error("登录状态已失效，请重新登录。");
  }
  return response;
}
