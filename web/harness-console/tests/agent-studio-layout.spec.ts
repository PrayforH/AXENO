import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

const page = readFileSync(
  join(process.cwd(), "src/app/studio/agents/page.tsx"),
  "utf8",
);
const workbench = readFileSync(
  join(
    process.cwd(),
    "src/components/agent-studio/agent-studio-workbench.tsx",
  ),
  "utf8",
);
const styles = readFileSync(
  join(process.cwd(), "src/components/agent-studio/agent-studio.module.css"),
  "utf8",
);
const studioConfig = readFileSync(
  join(process.cwd(), "src/lib/agent-studio.ts"),
  "utf8",
);

describe("Agent Studio management page", () => {
  it("is an independent control-plane route", () => {
    expect(page).toContain("AgentStudioWorkbench");
    expect(workbench).toContain("Agent Studio");
    expect(workbench).toContain("有效运行契约");
    expect(workbench).toContain("返回任务工作台");
    expect(workbench).toContain('data-studio-integration="pending-auth"');
  });

  it("organizes authoring as a capability chain instead of one giant form", () => {
    for (const label of [
      "基本信息",
      "System Prompt",
      "Skills",
      "Tools 与联网",
      "运行与权限",
      "测试与发布",
    ]) {
      expect(workbench).toContain(label);
    }
    for (const node of ["Model", "Prompt", "Skills", "Tools", "Isolation", "Release"]) {
      expect(workbench).toContain(`label="${node}"`);
    }
    expect(styles).toContain(".capabilitySpine");
  });

  it("keeps sandbox mandatory and presents Tavily as bounded external egress", () => {
    expect(workbench).toContain("隔离是生产基线，不是 Agent 开关");
    expect(workbench).toContain("隔离执行 · 平台托管");
    expect(workbench).toContain("生产强制");
    expect(workbench).not.toContain('type="checkbox" checked={sandbox');
    expect(studioConfig).toContain("公网搜索（Tavily）");
    expect(workbench).toContain("这不会开放任意 Bash 网络访问");
  });

  it("does not pretend publishing works before authentication integration", () => {
    expect(workbench).toContain("等待登录与 RBAC 分支接入");
    expect(workbench).toMatch(/className=\{styles\.publishButton\}[\s\S]*?disabled/);
  });

  it("uses a quiet registry palette with no decorative gradient", () => {
    expect(styles).not.toContain("linear-gradient");
    expect(styles).not.toContain("radial-gradient");
    expect(styles).toContain("--studio-green: #2e7058");
    expect(styles).toContain("--studio-violet: #655a82");
    expect(styles).toMatch(/@media \(max-width: 900px\)/);
    expect(styles).toMatch(/@media \(prefers-reduced-motion: no-preference\)/);
  });
});
