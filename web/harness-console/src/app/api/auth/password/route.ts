import { authenticatedAuthMutation } from "../../../../lib/auth-route";

export async function POST(request: Request): Promise<Response> {
  return authenticatedAuthMutation(request, "password", {
    clearSessionOnSuccess: true,
  });
}
