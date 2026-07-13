import { describe, expect, it } from "vitest";
import { runtimeDisclaimer } from "../src/lib/runtime-label";

describe("runtime disclaimer", () => {
  it("identifies cc-switch backed Claude SDK mode", () => {
    expect(runtimeDisclaimer("claude-sdk")).toBe(
      "Claude SDK · cc-switch · Langfuse 默认关闭",
    );
  });

  it("keeps Fake Runtime as the safe default", () => {
    expect(runtimeDisclaimer(undefined)).toBe(
      "本地 Fake Runtime · Langfuse 默认关闭",
    );
  });
});
