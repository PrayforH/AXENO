import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

describe("assistant-ui AG-UI runtime", () => {
  it("uses the same-origin Harness boundary without CopilotKit", () => {
    const shell = readFileSync(
      join(process.cwd(), "src/components/assistant-runtime-shell.tsx"),
      "utf8",
    );

    expect(shell).toContain('url: "/api/agui"');
    expect(shell).toContain("useAgUiRuntime");
    expect(shell).toContain("createInputAttachmentAdapter");
    expect(shell).not.toContain("CopilotKit");
  });
});
