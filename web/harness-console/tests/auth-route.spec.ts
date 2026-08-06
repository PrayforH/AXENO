import { afterEach, describe, expect, it, vi } from "vitest";
import {
  authenticatedAuthMutation,
  authenticatedAuthProxy,
} from "../src/lib/auth-route";

afterEach(() => {
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
});

describe("authenticated workspace member requests", () => {
  it("forwards member listing and role updates through the user session", async () => {
    vi.stubEnv("HARNESS_API_URL", "http://harness.internal:8000");
    const calls: Array<{ url: string; method: string; body?: string }> = [];
    vi.stubGlobal("fetch", async (input: RequestInfo | URL, init?: RequestInit) => {
      calls.push({
        url: String(input),
        method: String(init?.method),
        body: typeof init?.body === "string" ? init.body : undefined,
      });
      return Response.json([]);
    });

    await authenticatedAuthProxy(
      new Request("http://console.test/api/auth/members", {
        headers: { Cookie: "harness_access_token=user-jwt" },
      }),
      "members",
    );
    await authenticatedAuthProxy(
      new Request("http://console.test/api/auth/members/user-2", {
        method: "PATCH",
        headers: { Cookie: "harness_access_token=user-jwt" },
        body: JSON.stringify({ role: "admin" }),
      }),
      "members/user-2",
    );

    expect(calls).toEqual([
      {
        url: "http://harness.internal:8000/v1/auth/members",
        method: "GET",
      },
      {
        url: "http://harness.internal:8000/v1/auth/members/user-2",
        method: "PATCH",
        body: '{"role":"admin"}',
      },
    ]);
  });
});

describe("authenticated account mutations", () => {
  it("forwards profile updates with the signed user token", async () => {
    vi.stubEnv("HARNESS_API_URL", "http://harness.internal:8000");
    let receivedUrl = "";
    let receivedInit: RequestInit | undefined;
    vi.stubGlobal("fetch", async (input: RequestInfo | URL, init?: RequestInit) => {
      receivedUrl = String(input);
      receivedInit = init;
      return Response.json({ display_name: "New Name" });
    });

    const response = await authenticatedAuthMutation(
      new Request("http://console.test/api/auth/profile", {
        method: "PATCH",
        headers: {
          "Content-Type": "application/json",
          Cookie: "harness_access_token=user-jwt",
        },
        body: JSON.stringify({ display_name: "New Name" }),
      }),
      "me",
    );

    expect(receivedUrl).toBe("http://harness.internal:8000/v1/auth/me");
    expect(receivedInit?.method).toBe("PATCH");
    expect(new Headers(receivedInit?.headers).get("Authorization")).toBe(
      "Bearer user-jwt",
    );
    expect(await response.json()).toEqual({ display_name: "New Name" });
  });

  it("clears browser credentials after a successful password change", async () => {
    vi.stubEnv("HARNESS_API_URL", "http://harness.internal:8000");
    vi.stubGlobal("fetch", async () => new Response(null, { status: 204 }));

    const response = await authenticatedAuthMutation(
      new Request("http://console.test/api/auth/password", {
        method: "POST",
        headers: { Cookie: "harness_access_token=user-jwt" },
        body: JSON.stringify({
          current_password: "CurrentPass123",
          new_password: "NewSecurePass456",
        }),
      }),
      "password",
      { clearSessionOnSuccess: true },
    );

    expect(response.status).toBe(204);
    const cookies = response.headers.get("set-cookie") ?? "";
    expect(cookies).toContain("harness_access_token=");
    expect(cookies).toContain("harness_refresh_token=");
    expect(cookies).toContain("Max-Age=0");
  });
});
