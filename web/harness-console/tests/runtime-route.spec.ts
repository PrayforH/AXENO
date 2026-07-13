import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

describe("CopilotKit runtime route", () => {
  it("forces REST transport to match the multi-route runtime handler", () => {
    const shell = readFileSync(
      join(
      process.cwd(),
        "src/components/copilotkit-shell.tsx",
      ),
      "utf8",
    );

    expect(shell).toContain("useSingleEndpoint={false}");
  });
});
