import { logoutSession } from "../../../../lib/auth-route";

export async function POST(request: Request): Promise<Response> {
  return logoutSession(request);
}

export async function GET(request: Request): Promise<Response> {
  return logoutSession(request);
}
