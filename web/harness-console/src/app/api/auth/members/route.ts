import { authenticatedAuthProxy } from "../../../../lib/auth-route";

export const dynamic = "force-dynamic";

export async function GET(request: Request): Promise<Response> {
  return authenticatedAuthProxy(request, "members");
}
