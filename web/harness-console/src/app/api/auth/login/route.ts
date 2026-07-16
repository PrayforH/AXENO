import { credentialAuth } from "../../../../lib/auth-route";

export async function POST(request: Request): Promise<Response> {
  return credentialAuth(request, "login");
}
