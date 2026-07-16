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

  it("keeps the immutable Agent coordinate in server configuration", () => {
    const page = readFileSync(join(process.cwd(), "src/app/page.tsx"), "utf8");
    const config = readFileSync(
      join(process.cwd(), "src/lib/server-config.ts"),
      "utf8",
    );

    expect(page).not.toContain("echo-agent");
    expect(page).not.toContain("0.4.0");
    expect(config).toContain('environment.HARNESS_AGENT_NAME ?? "echo-agent"');
    expect(config).toContain('environment.HARNESS_AGENT_VERSION ?? "0.4.0"');
  });
});
