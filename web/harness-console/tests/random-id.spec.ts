import { afterEach, describe, expect, it, vi } from "vitest";
import { createRandomId } from "../src/lib/random-id";

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("createRandomId", () => {
  it("uses randomUUID when the secure-context API is available", () => {
    vi.stubGlobal("crypto", {
      randomUUID: () => "00000000-0000-4000-8000-000000000001",
    });

    expect(createRandomId()).toBe("00000000-0000-4000-8000-000000000001");
  });

  it("creates an RFC 4122 version 4 id without randomUUID", () => {
    vi.stubGlobal("crypto", {
      getRandomValues: (bytes: Uint8Array) => {
        bytes.fill(0x11);
        return bytes;
      },
    });

    expect(createRandomId()).toBe("11111111-1111-4111-9111-111111111111");
  });

  it("still creates an id when Web Crypto is unavailable", () => {
    vi.stubGlobal("crypto", undefined);

    expect(createRandomId()).toMatch(
      /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/,
    );
  });
});
