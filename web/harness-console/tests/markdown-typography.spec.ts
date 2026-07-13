import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

const styles = readFileSync(join(process.cwd(), "src/app/styles.css"), "utf8");

describe("assistant Markdown typography", () => {
  it("keeps Streamdown prose on the harness reading scale", () => {
    expect(styles).toContain("/* Assistant Markdown typography */");
    expect(styles).toMatch(
      /\.chat-surface \[data-testid="copilot-assistant-message"\] \.space-y-4\.whitespace-normal[^{]*\{[^}]*font-size:\s*15px;[^}]*line-height:\s*1\.65;/s,
    );
    expect(styles).toMatch(
      /:where\(\.chat-surface \[data-testid="copilot-assistant-message"\] \.space-y-4\.whitespace-normal > \*\)[^{]*\{[^}]*margin-block:\s*0;/s,
    );
    expect(styles).toMatch(
      /\[data-streamdown="heading-2"\][^{]*\{[^}]*margin:\s*22px 0 8px;[^}]*font-size:\s*19px;[^}]*line-height:\s*1\.4;/s,
    );
    expect(styles).toMatch(
      /\[data-streamdown="unordered-list"\][^{]*\{[^}]*list-style-position:\s*outside;/s,
    );
    expect(styles).toMatch(
      /\[data-streamdown="blockquote"\] > p[^{]*\{[^}]*margin:\s*0;/s,
    );
    expect(styles).toMatch(
      /\[data-streamdown="code-block-body"\][^{]*\{[^}]*font-size:\s*13px;[^}]*line-height:\s*1\.6;/s,
    );
    expect(styles).toMatch(
      /\[data-streamdown="code-block-body"\] > code[^{]*\{[^}]*counter-reset:\s*harness-code-line;/s,
    );
    expect(styles).toMatch(
      /\[data-streamdown="code-block-body"\] > code > span[^{]*\{[^}]*display:\s*block;[^}]*counter-increment:\s*harness-code-line;/s,
    );
    expect(styles).toMatch(
      /\[data-streamdown="code-block-download-button"\][^{]*\{[^}]*display:\s*none;/s,
    );
    expect(styles).toMatch(
      /\[data-streamdown="code-block-copy-button"\][^{]*\{[^}]*width:\s*32px;[^}]*height:\s*32px;/s,
    );
    expect(styles).toMatch(
      /\[data-testid="copilot-assistant-toolbar"\][^{]*\{[^}]*justify-content:\s*flex-end;[^}]*opacity:\s*0\.55;/s,
    );
  });
});
