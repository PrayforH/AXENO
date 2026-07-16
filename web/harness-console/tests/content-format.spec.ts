import { describe, expect, it } from "vitest";
import {
  classifyContent,
  toSafeValue,
  truncateLines,
} from "../src/lib/content-format";

describe("agent content formatting", () => {
  it("classifies objects and JSON strings", () => {
    expect(classifyContent({ ok: true }).kind).toBe("json");
    expect(classifyContent('{"answer":42}')).toEqual({
      kind: "json",
      value: { answer: 42 },
    });
  });

  it("extracts fenced code and unified diffs", () => {
    expect(classifyContent("```python\nprint('ok')\n```")).toEqual({
      kind: "code",
      language: "python",
      value: "print('ok')",
    });
    expect(classifyContent("--- a/file\n+++ b/file\n@@ -1 +1 @@\n-old\n+new").kind).toBe(
      "diff",
    );
  });

  it("truncates long logs with an explicit count", () => {
    expect(truncateLines("a\nb\nc", 2)).toEqual({
      value: "a\nb",
      truncated: 1,
    });
  });

  it("normalizes circular objects without throwing", () => {
    const value: { self?: unknown } = {};
    value.self = value;

    expect(toSafeValue(value)).toEqual({ self: "[Circular]" });
  });
});
