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
const studioClient = readFileSync(
  join(process.cwd(), "src/lib/studio-client.ts"),
  "utf8",
);
const errorBoundary = readFileSync(
  join(process.cwd(), "src/app/studio/agents/error.tsx"),
  "utf8",
);
const loadingBoundary = readFileSync(
  join(process.cwd(), "src/app/studio/agents/loading.tsx"),
  "utf8",
);

describe("Agent Studio management page", () => {
  it("is an independent control-plane route", () => {
    expect(page).toContain("AgentStudioWorkbench");
    expect(workbench).toContain("Agent Studio");
    expect(workbench).toContain("有效运行契约");
    expect(workbench).toContain('aria-label="工作区"');
    expect(workbench).toContain('href="/"');
    expect(workbench).toContain('href="/studio/agents"');
    expect(page).toContain("AuthProvider");
    expect(workbench).toContain('data-studio-integration="api"');
  });

  it("organizes authoring as a capability chain instead of one giant form", () => {
    for (const label of [
      "基本信息",
      "System Prompt",
      "协同编排",
      "Skills",
      "Tools 与联网",
      "运行与权限",
      "测试与发布",
    ]) {
      expect(workbench).toContain(label);
    }
    for (const node of ["Model", "Prompt", "Skills", "Tools", "Agents", "Isolation", "Release"]) {
      expect(workbench).toContain(`label="${node}"`);
    }
    expect(styles).toContain(".capabilitySpine");
  });

  it("shows a Lead topology with editable, version-pinned Sub Agent roles", () => {
    expect(workbench).toContain('aria-label="多智能体协同拓扑"');
    expect(workbench).toContain("Lead 是唯一面向用户的主线");
    expect(workbench).toContain("value={contract.collaborationLabel}");
    expect(workbench).toContain("固定版本引用");
    expect(workbench).toContain("允许后台并行");
    expect(workbench).toContain("同一通用 Agent 版本可绑定多个职责");
    expect(workbench).toContain("从已发布目录选择");
    expect(workbench).toContain("协同运行摘要");
    expect(workbench).toContain("publishedSubagents");
    expect(studioClient).toContain("publishedVersion");
    expect(styles).toContain(".orchestrationGraph");
    expect(styles).toContain(".subagentTopology");
    expect(styles).toContain(".leadAgentCard");
  });

  it("keeps sandbox mandatory and presents Tavily as bounded external egress", () => {
    expect(workbench).toContain("隔离是生产基线，不是 Agent 开关");
    expect(workbench).toContain("隔离执行 · 平台托管");
    expect(workbench).toContain("生产强制");
    expect(workbench).not.toContain('type="checkbox" checked={sandbox');
    expect(studioConfig).toContain("公网搜索（Tavily）");
    expect(workbench).toContain("这不会开放任意 Bash 网络访问");
    expect(workbench).toContain("独立工作负载身份");
    expect(workbench).toContain("恢复同一会话的 SDK 上下文");
    expect(workbench).toContain("不宣称支持任意工具步骤的持久化 checkpoint");
  });

  it("uses authenticated roles and keeps publication disabled until governance is ready", () => {
    expect(workbench).toContain("membership.role");
    expect(workbench).toContain("发布治理将在下一阶段接入");
    expect(workbench).toMatch(/className=\{styles\.publishButton\}[\s\S]*?disabled/);
  });

  it("makes the draft-to-deployment lifecycle explicit without hiding failures", () => {
    expect(workbench).toContain('aria-label="从草稿到部署的生命周期"');
    for (const label of ["隔离试跑", "不可变 Bundle", "按环境晋级"]) {
      expect(workbench).toContain(label);
    }
    expect(workbench).toContain("离线轨迹评测");
    expect(workbench).toContain("线上质量监控");
    expect(workbench).toContain("必须调用");
    expect(workbench).toContain("禁止");
    expect(errorBoundary).toContain("Studio 没有正常加载");
    expect(errorBoundary).toContain("重新加载");
    expect(loadingBoundary).toContain("正在恢复 Agent Studio");
    expect(styles).toContain(".studioStateShell");
  });

  it("renders only tenant API rows instead of invented live agents", () => {
    expect(workbench).toContain("租户控制面");
    expect(workbench).toContain("studioClient.listDrafts");
    expect(workbench).toContain("studioClient.getDraft");
    expect(workbench).not.toContain("helper-agent-1.0.0");
    expect(workbench).not.toContain("echo-agent-0.4.0");
    expect(workbench).not.toContain("合同审查助手");
    expect(workbench).not.toContain("工单分诊助手");
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
