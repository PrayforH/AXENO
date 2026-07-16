import { authenticatedAuthMutation } from "../../../../lib/auth-route";

export async function PATCH(request: Request): Promise<Response> {
  return authenticatedAuthMutation(request, "me");
}
