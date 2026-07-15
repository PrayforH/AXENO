import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

const chatPage = readFileSync(join(process.cwd(), "src/app/chat/page.tsx"), "utf8");
const page = readFileSync(join(process.cwd(), "src/app/page.tsx"), "utf8");
const styles = readFileSync(join(process.cwd(), "src/app/styles.css"), "utf8");

describe("full-page agent workbench", () => {
  it("presents a user task workspace instead of an internal validation console", () => {
    expect(chatPage).toContain("Agent Workspace");
    expect(chatPage).toContain("智能任务助手");
    expect(chatPage).toContain("新任务");
    expect(chatPage).toContain("本次运行");
    expect(chatPage).not.toContain("交互验证台");
    expect(chatPage).not.toContain("切换开发者信息");
    expect(chatPage).not.toContain("developerMode");
  });

  it("removes the decorative live rail and hard-coded agent coordinate", () => {
    expect(chatPage).not.toContain("run-rail");
    expect(chatPage).not.toContain(">LIVE<");
    expect(chatPage).not.toContain("echo-agent");
    expect(chatPage).not.toContain("0.3.0");
  });

  it("uses a dense centered conversation and compact sticky controls", () => {
    expect(styles).toMatch(
      /\.chat-stage\s*\{[^}]*grid-template-columns:\s*minmax\(0,\s*1fr\);/s,
    );
    expect(styles).toMatch(
      /\.aui-thread-root\s*\{[^}]*--aui-thread-max-width:\s*57\.5rem;/s,
    );
    expect(styles).toMatch(/\.console-header\s*\{[^}]*min-height:\s*56px;/s);
    expect(styles).toMatch(
      /\.aui-thread-viewport-footer\s*\{[^}]*position:\s*sticky;/s,
    );
    expect(styles).not.toContain("linear-gradient");
  });

  it("styles a task brief instead of a generic chat welcome", () => {
    expect(styles).toMatch(
      /\.user-task-welcome\s*\{[^}]*max-width:\s*var\(--aui-thread-max-width\);/s,
    );
    expect(styles).toMatch(
      /\.user-task-grid\s*\{[^}]*grid-template-columns:\s*repeat\(3,\s*minmax\(0,\s*1fr\)\);/s,
    );
    expect(styles).toMatch(
      /@media\s*\(max-width:\s*680px\)[\s\S]*?\.user-task-grid\s*\{[^}]*grid-template-columns:\s*1fr;/s,
    );
  });

  it("removes obsolete custom thread layout rules superseded by assistant-ui", () => {
    for (const selector of [
      ".aui-welcome {",
      ".aui-message-list {",
      ".aui-message {",
      ".aui-viewport-footer {",
      ".aui-composer {",
    ]) {
      expect(styles).not.toContain(selector);
    }
    expect(styles).toContain(".aui-thread-root");
    expect(styles).toContain(".aui-composer-root");
  });

  it("visually recedes a completed execution ribbon", () => {
    expect(styles).toMatch(
      /\.execution-ribbon\.phase-completed\s*\{[^}]*opacity:\s*0\.[0-9]+;/s,
    );
  });

  it("shows a lightweight recovery skeleton instead of a lone loading line", () => {
    expect(chatPage).toContain('className="chat-loading-skeleton"');
    expect(chatPage).toContain('aria-busy="true"');
    expect(styles).toContain(".chat-loading-skeleton");
    expect(styles).toContain(".chat-loading-line");
  });

  it("keeps primary touch targets at least 40px high", () => {
    expect(styles).toMatch(
      /\.quiet-button,\s*\.icon-button\s*\{[^}]*min-height:\s*40px;/s,
    );
    expect(styles).toMatch(
      /\.inspector-close\s*\{[^}]*width:\s*40px;[^}]*height:\s*40px;/s,
    );
    expect(styles).toMatch(
      /\.harness-composer-shell \.aui-composer-attach,[\s\S]*?min-height:\s*40px;/s,
    );
    expect(styles).toMatch(
      /@media \(max-width: 720px\)[\s\S]*?button,\s*summary\s*\{[^}]*min-height:\s*40px !important;/s,
    );
    expect(styles).toMatch(
      /@media \(max-width: 720px\)[\s\S]*?\.preview-button,\s*\.download-button\s*\{[^}]*min-height:\s*40px;/s,
    );
  });

  it("redirects root to the chat page", () => {
    expect(page).toContain('redirect("/chat")');
  });
});
