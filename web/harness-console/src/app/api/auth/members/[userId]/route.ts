import { authenticatedAuthProxy } from "../../../../../lib/auth-route";

export async function PATCH(
  request: Request,
  context: { params: Promise<{ userId: string }> },
): Promise<Response> {
  const { userId } = await context.params;
  return authenticatedAuthProxy(request, `members/${encodeURIComponent(userId)}`);
}
