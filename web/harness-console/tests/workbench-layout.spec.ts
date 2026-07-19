import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

const page = readFileSync(join(process.cwd(), "src/app/page.tsx"), "utf8");
const styles = readFileSync(join(process.cwd(), "src/app/styles.css"), "utf8");
const taskSidebar = readFileSync(
  join(process.cwd(), "src/components/task-sidebar.tsx"),
  "utf8",
);
const workspaceNavigation = readFileSync(
  join(process.cwd(), "src/components/workspace-navigation.tsx"),
  "utf8",
);
const workspaceNavigationStyles = readFileSync(
  join(process.cwd(), "src/components/workspace-navigation.module.css"),
  "utf8",
);

describe("full-page agent workbench", () => {
  it("presents a user task workspace instead of an internal validation console", () => {
    expect(page).toContain("Agent Studio");
    expect(page).not.toContain("Agent Harness");
    expect(page).not.toContain('<span>新任务</span>');
    expect(page).toContain("运行详情");
    expect(page).not.toContain("交互验证台");
    expect(page).not.toContain("切换开发者信息");
    expect(page).not.toContain("developerMode");
  });

  it("keeps collapse and expand controls inside the task rail", () => {
    expect(page).not.toContain('className="icon-button task-sidebar-toggle"');
    expect(page).toContain("collapsed={!taskSidebarOpen}");
    expect(taskSidebar).toContain('className="task-sidebar-rail"');
    expect(taskSidebar).toContain('aria-label="收起任务列表"');
    expect(taskSidebar).toContain('aria-label="展开任务列表"');
    expect(taskSidebar).toContain("<WorkspaceCollapseIcon collapsed={false} />");
    expect(taskSidebar).toContain("<WorkspaceCollapseIcon collapsed />");
    expect(styles).toMatch(
      /\.workspace-stage:not\(\.tasks-open\)\s*\{[^}]*grid-template-columns:\s*52px minmax\(0,\s*1fr\);/s,
    );
  });

  it("uses the same focused workspace destinations in both sidebars", () => {
    expect(taskSidebar).toContain('<WorkspaceNavigation active="tasks" />');
    expect(taskSidebar).toContain('<WorkspaceNavigation active="tasks" collapsed />');
    for (const [href, label] of [
      ["/", "任务"],
      ["/studio/agents", "智能体"],
      ["/studio/data", "数据"],
    ]) {
      expect(workspaceNavigation).toContain(`href: "${href}"`);
      expect(workspaceNavigation).toContain(`label: "${label}"`);
    }
    expect(workspaceNavigation).not.toContain('href: "/studio/usage"');
    expect(workspaceNavigation).not.toContain('label: "用量"');
    expect(workspaceNavigationStyles).toContain(".navigationActive");
    expect(workspaceNavigationStyles).toContain(
      '[data-workspace-navigation="collapsed"]',
    );
  });

  it("projects task approvals into the composer surface", () => {
    expect(taskSidebar).toContain("approvalStore.reset()");
    expect(taskSidebar).toContain("approvalStore.show(selected.pending_approval)");
    expect(taskSidebar).toContain('runView?.phase !== "waiting_approval"');
    expect(taskSidebar).toContain("[refreshToken, runView?.phase]");
    expect(taskSidebar).not.toContain("task-approval-panel");
  });

  it("removes the decorative live rail and hard-coded agent coordinate", () => {
    expect(page).not.toContain("run-rail");
    expect(page).not.toContain(">LIVE<");
    expect(page).not.toContain("echo-agent");
    expect(page).not.toContain("0.4.0");
  });

  it("uses a dense centered conversation and compact sticky controls", () => {
    expect(styles).toMatch(
      /\.chat-stage\s*\{[^}]*grid-template-columns:\s*minmax\(0,\s*1fr\);/s,
    );
    expect(styles).toMatch(
      /\.aui-thread-root\s*\{[^}]*--aui-thread-max-width:\s*50rem;/s,
    );
    expect(styles).toMatch(/\.console-header\s*\{[^}]*min-height:\s*52px;/s);
    expect(styles).toMatch(
      /\.aui-thread-viewport-footer\s*\{[^}]*position:\s*sticky;/s,
    );
    expect(styles).not.toContain("linear-gradient");
  });

  it("styles a task brief instead of a generic chat welcome", () => {
    expect(styles).toMatch(
      /\.user-task-welcome\s*\{[^}]*max-width:\s*46rem;/s,
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

  it("renders completed execution as a quiet Codex-style processed row", () => {
    expect(styles).toMatch(
      /\.execution-ribbon\.phase-completed\s*\{[^}]*border:\s*0;[^}]*background:\s*transparent;[^}]*opacity:\s*1;/s,
    );
    expect(styles).toMatch(
      /\.execution-ribbon\.phase-completed \.execution-state-mark,[\s\S]*?display:\s*none;/s,
    );
    expect(styles).toMatch(
      /\.execution-ribbon\s*>\s*summary\s*\{[^}]*border-bottom:\s*1px solid #e2e4e1;/s,
    );
  });

  it("keeps short user messages horizontal and the composer focus treatment neutral", () => {
    expect(styles).toMatch(
      /\.aui-user-message-root\s*\{[^}]*display:\s*flex;[^}]*align-items:\s*flex-end;/s,
    );
    expect(styles).toMatch(
      /\.aui-user-message-content\s*\{[^}]*width:\s*auto;[^}]*flex:\s*0 1 auto;/s,
    );
    expect(styles).toMatch(
      /\.harness-composer-shell \.aui-composer-input:focus-visible\s*\{[^}]*outline:\s*none;/s,
    );
    expect(styles).not.toContain("border-color: #d9c5a7");
  });

  it("aligns user message actions beneath the right-aligned bubble", () => {
    expect(styles).toMatch(
      /\.harness-user-message\s*\{[^}]*position:\s*relative;[^}]*padding:\s*12px 0 0;/s,
    );
    expect(styles).toMatch(
      /\.harness-user-action-bar\s*\{[^}]*position:\s*absolute;[^}]*top:\s*calc\(100% \+ 1px\);[^}]*right:\s*2px;[^}]*gap:\s*2px;/s,
    );
    expect(styles).toMatch(
      /\.harness-user-action-bar\s*\{[^}]*opacity:\s*0;[^}]*pointer-events:\s*none;/s,
    );
    expect(styles).toMatch(
      /\.harness-user-message:hover \.harness-user-action-bar,[\s\S]*?opacity:\s*1;[\s\S]*?pointer-events:\s*auto;/s,
    );
    expect(styles).toMatch(
      /\.user-message-action\s*\{[^}]*width:\s*28px;[^}]*height:\s*28px;/s,
    );
    expect(styles).toMatch(
      /\.harness-user-message \+ \.harness-assistant-message\s*\{[^}]*padding-top:\s*35px;/s,
    );
  });

  it("keeps the attachment control close to the composer text", () => {
    expect(styles).toMatch(
      /\.harness-composer-shell \.aui-composer-root\s*\{[^}]*column-gap:\s*0;/s,
    );
    expect(styles).toMatch(
      /\.harness-composer-shell \.aui-composer-input\s*\{[^}]*padding:\s*8px 8px 8px 2px;/s,
    );
  });

  it("shows an explicit inline editor for message reruns", () => {
    expect(styles).toMatch(
      /\.user-message-editor\s*\{[^}]*width:\s*min\(100%,\s*48rem\);[^}]*align-self:\s*flex-end;[^}]*border-radius:\s*20px;[^}]*background:\s*#f1f2f1;/s,
    );
    expect(styles).toMatch(
      /\.user-message-editor-actions button:last-child\s*\{[^}]*background:\s*#202522;/s,
    );
  });

  it("keeps restored per-turn processing above the answer and collapsed", () => {
    expect(styles).toMatch(
      /\.turn-activity-summary\s*\{[^}]*order:\s*-10;[^}]*width:\s*100%;/s,
    );
  });

  it("centers composer controls on one shared vertical axis", () => {
    expect(styles).toMatch(
      /\.harness-composer-shell \.aui-composer-root\s*\{[^}]*min-height:\s*58px;[^}]*align-items:\s*center;/s,
    );
    expect(styles).toMatch(
      /\.harness-composer-shell \.aui-composer-input\s*\{[^}]*min-height:\s*40px;[^}]*padding:\s*8px 8px 8px 2px;[^}]*line-height:\s*24px;/s,
    );
    expect(styles).toMatch(
      /\.harness-composer-shell \.aui-composer-attach,[\s\S]*?width:\s*40px;[^}]*height:\s*40px;[^}]*margin:\s*0;[^}]*align-items:\s*center;[^}]*justify-content:\s*center;/s,
    );
    expect(styles).toMatch(
      /\.composer-meta\s*\{[^}]*padding:\s*6px 10px 0;[^}]*align-items:\s*center;/s,
    );
  });

  it("uses a single-column assistant flow so errors cannot occupy an avatar grid cell", () => {
    expect(styles).toMatch(
      /\.aui-assistant-message-root\s*\{[^}]*display:\s*flex;[^}]*flex-direction:\s*column;[^}]*align-items:\s*stretch;/s,
    );
    expect(styles).toMatch(
      /\.aui-assistant-message-content\s*\{[^}]*width:\s*100%;[^}]*max-width:\s*none;[^}]*margin:\s*0;/s,
    );
  });

  it("keeps assistant actions below the answer instead of floating over activity", () => {
    expect(styles).toMatch(
      /\.harness-assistant-message\s*>\s*\.aui-assistant-message-content\s*\{[^}]*order:\s*1;/s,
    );
    expect(styles).toMatch(
      /\.harness-assistant-message\s*>\s*\.assistant-message-controls\s*\{[^}]*order:\s*3;/s,
    );
    expect(styles).toMatch(
      /\.assistant-message-controls\s*\{[^}]*min-height:\s*28px;[^}]*display:\s*flex;/s,
    );
    expect(styles).toMatch(
      /\.assistant-message-controls\s*>\s*\.aui-assistant-action-bar-root\[data-floating\]\s*\{[^}]*position:\s*static;[^}]*border:\s*0;[^}]*box-shadow:\s*none;/s,
    );
  });

  it("keeps wide Markdown tables inside a keyboard-scrollable region", () => {
    const markdown = readFileSync(
      join(process.cwd(), "src/components/markdown-text.tsx"),
      "utf8",
    );
    expect(markdown).toContain('className="aui-table-scroll"');
    expect(markdown).toContain('aria-label="表格，可横向滚动"');
    expect(markdown).toContain("table: ScrollableTable");
    expect(markdown).not.toContain("defer");
    expect(markdown).toContain("smooth={codexStreamSmoothing}");
    expect(markdown).toContain("drainMs: 320");
    expect(markdown).toContain("maxCharsPerFrame: 12");
    expect(markdown).toContain("minCommitMs: 32");
    expect(styles).toMatch(
      /\.aui-table-scroll\s*\{[^}]*overflow-x:\s*auto;/s,
    );
    expect(styles).toMatch(
      /\.aui-table-scroll table\s*\{[^}]*width:\s*max-content;[^}]*min-width:\s*100%;/s,
    );
  });

  it("reserves a real desktop grid column for run details", () => {
    expect(styles).toMatch(
      /@media \(max-width: 1100px\) and \(min-width: 981px\)[\s\S]*?\.workspace-stage\.tasks-open\.inspector-open\s*\{[^}]*grid-template-columns:\s*244px minmax\(0,\s*1fr\) 320px;/s,
    );
    expect(styles).toMatch(
      /@media \(max-width: 1100px\) and \(min-width: 981px\)[\s\S]*?\.workspace-stage\.tasks-open\.inspector-open \.developer-drawer\s*\{[^}]*position:\s*relative;[^}]*width:\s*auto;/s,
    );
  });

  it("shows a lightweight recovery skeleton instead of a lone loading line", () => {
    expect(page).toContain('className="chat-loading-skeleton"');
    expect(page).toContain('aria-busy="true"');
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
});
