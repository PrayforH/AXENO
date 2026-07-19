import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

const menu = readFileSync(
  join(process.cwd(), "src/components/account-menu.tsx"),
  "utf8",
);
const settings = readFileSync(
  join(process.cwd(), "src/app/settings/page.tsx"),
  "utf8",
);
const taskSidebar = readFileSync(
  join(process.cwd(), "src/components/task-sidebar.tsx"),
  "utf8",
);
const studioSidebar = readFileSync(
  join(process.cwd(), "src/components/agent-studio/studio-sidebar.tsx"),
  "utf8",
);
const workbench = readFileSync(join(process.cwd(), "src/app/page.tsx"), "utf8");
const styles = readFileSync(join(process.cwd(), "src/app/styles.css"), "utf8");

describe("account settings", () => {
  it("keeps settings and logout available from the account menu", () => {
    expect(menu).toContain('href="/settings"');
    expect(menu).toContain("个人设置");
    expect(menu).toContain('href="/api/auth/logout"');
    expect(menu).toContain("退出登录");
  });

  it("anchors the user control at the bottom of expanded and collapsed task rails", () => {
    expect(taskSidebar).toContain('className="task-sidebar-account"');
    expect(taskSidebar).toContain('className="task-rail-account"');
    expect(taskSidebar.match(/<AccountMenu \/>/g)).toHaveLength(2);
    expect(studioSidebar).toContain("<AccountMenu />");
    expect(workbench).not.toContain("<AccountMenu />");
    expect(styles).toMatch(/\.task-rail-account\s*\{[^}]*margin-top:\s*auto;/s);
    expect(styles).toMatch(/\.account-popover\s*\{[^}]*bottom:\s*calc\(100% \+ 8px\);[^}]*left:\s*0;/s);
  });

  it("provides useful profile, password, and session controls", () => {
    expect(settings).toContain("个人资料");
    expect(settings).toContain("修改密码");
    expect(settings).toContain("登录会话");
    expect(settings).toContain('fetch("/api/auth/profile"');
    expect(settings).toContain('fetch("/api/auth/password"');
    expect(settings).toContain("修改密码后会撤销所有刷新会话");
  });

  it("keeps the settings page responsive and visually restrained", () => {
    expect(styles).toMatch(/\.settings-layout\s*\{[^}]*grid-template-columns:\s*160px minmax\(0,\s*760px\);/s);
    expect(styles).toMatch(/@media \(max-width: 760px\)[\s\S]*?\.settings-layout\s*\{[^}]*display:\s*block;/s);
    expect(styles).not.toContain(".settings-shell {\n  background: linear-gradient");
  });
});
