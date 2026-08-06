import { describe, expect, it, vi } from "vitest";
import { redirectOnUnauthorized } from "../src/lib/client-auth";

describe("client authentication response handling", () => {
  it("redirects an expired session to login", () => {
    const replace = vi.fn();

    expect(
      redirectOnUnauthorized(new Response(null, { status: 401 }), { replace }),
    ).toBe(true);
    expect(replace).toHaveBeenCalledWith("/login?error=session_expired");
  });

  it("does not redirect for a non-authentication failure", () => {
    const replace = vi.fn();

    expect(
      redirectOnUnauthorized(new Response(null, { status: 503 }), { replace }),
    ).toBe(false);
    expect(replace).not.toHaveBeenCalled();
  });
});
