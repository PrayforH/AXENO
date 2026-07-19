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
const sidebar = readFileSync(
  join(process.cwd(), "src/components/agent-studio/studio-sidebar.tsx"),
  "utf8",
);
const sidebarStyles = readFileSync(
  join(
    process.cwd(),
    "src/components/agent-studio/studio-sidebar.module.css",
  ),
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
    expect(workbench).toContain("<StudioSidebar");
    expect(workbench).toContain("有效运行契约");
    expect(sidebar).toContain("Agent Studio");
    expect(sidebar).toContain("<WorkspaceNavigation");
    expect(workspaceNavigation).toContain('aria-label="工作区"');
    expect(workspaceNavigation).toContain('href: "/"');
    expect(workspaceNavigation).toContain('href: "/studio/agents"');
    expect(page).toContain("AuthProvider");
    expect(workbench).toContain('data-studio-integration="api"');
  });

  it("shares a persistent task-style collapsible control-plane rail", () => {
    expect(sidebar).toContain("agent-studio-sidebar-collapsed");
    expect(sidebar).toContain("data-studio-sidebar");
    expect(sidebar).toContain("收起 Agent Studio 侧栏");
    expect(sidebar).toContain("展开 Agent Studio 侧栏");
    expect(sidebar).toContain("aria-expanded={!collapsed}");
    expect(sidebar).not.toContain("<ThemeToggle");
    expect(sidebar).toContain("<AccountMenu");
    expect(sidebarStyles).toContain(
      '.sidebar[data-studio-sidebar="collapsed"]',
    );
    expect(sidebarStyles).toContain("width: 52px");
    expect(sidebarStyles).toContain("@media (max-width: 980px)");
    expect(workspaceNavigationStyles).toContain(".navigationActive");
    expect(workspaceNavigationStyles).toContain(
      '[data-workspace-navigation="collapsed"]',
    );
    expect(styles).toMatch(
      /@media \(max-width: 900px\)[\s\S]*?\.studioShell:has\(> \[data-studio-sidebar="collapsed"\]\)[\s\S]*?grid-template-columns: 52px minmax\(0, 1fr\)/,
    );
    expect(styles).toMatch(
      /@media \(max-width: 620px\)[\s\S]*?\.headerActions[\s\S]*?grid-template-columns: minmax\(0, 1fr\) auto auto/,
    );
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

  it("provides a structured prompt editor instead of an undifferentiated textarea", () => {
    expect(workbench).toContain('aria-label="System Prompt 结构"');
    expect(workbench).toContain("选择章节可定位");
    expect(workbench).toContain("专注编辑");
    expect(workbench).toContain("Ctrl / ⌘ S 保存");
    expect(workbench).toContain("moveToPromptSection");
    expect(workbench).toContain("handlePromptEditorKeyDown");
    expect(styles).toContain(".promptWorkspace");
    expect(styles).toContain(".promptEditorToolbar");
    expect(styles).toContain(".promptEditorFooter");
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

  it("keeps runtime and permission surfaces on shared light/dark theme tokens", () => {
    expect(styles).toMatch(
      /\.profileFacts span \{[\s\S]*?background: var\(--studio-panel-subtle\);/,
    );
    expect(styles).toMatch(
      /\.isolationCard \{[\s\S]*?background: var\(--studio-panel-subtle\);/,
    );
    expect(styles).toMatch(
      /\.identityBoundary,[\s\S]*?\.continuityBoundary \{[\s\S]*?background: var\(--studio-panel\);/,
    );
    expect(styles).toMatch(
      /\.identityBoundary header em,[\s\S]*?\.continuityBoundary header em \{[\s\S]*?background: var\(--studio-panel-subtle\);/,
    );
  });

  it("uses authenticated roles and gates immutable publication on server validation", () => {
    expect(workbench).toContain("membership.role");
    expect(workbench).toContain("studioClient.publishDraft");
    expect(workbench).toContain("请先通过服务端检查");
    expect(workbench).toContain("发布为不可覆盖的 Agent 版本");
    expect(workbench).toMatch(
      /className=\{styles\.publishButton\}[\s\S]*?disabled=\{!canPublish/,
    );
    expect(styles).toContain(".publicationBadge");
  });

  it("makes the draft-to-deployment lifecycle explicit without hiding failures", () => {
    expect(workbench).toContain('aria-label="从草稿到部署的生命周期"');
    for (const label of ["隔离试跑", "不可变 Bundle", "按环境晋级"]) {
      expect(workbench).toContain(label);
    }
    expect(workbench).toContain("固定版本轨迹评测");
    expect(workbench).toContain("耐久 Eval 控制面");
    expect(workbench).toContain("每个 Case 使用独立 Session");
    expect(workbench).toContain("downloadEvalArtifact");
    expect(workbench).toContain("线上质量监控");
    expect(workbench).toContain("规则 Score、人工反馈与 Alert");
    expect(workbench).toContain("外部同步失败独立重试");
    expect(workbench).toContain("studioClient.getQualityGate");
    expect(workbench).toContain("查看 Dashboard");
    expect(workbench).toContain("环境指针、灰度与可验证回滚");
    expect(workbench).toContain("新 Session 解析当前路由");
    expect(workbench).toContain("studioClient.promoteDeployment");
    expect(workbench).toContain("studioClient.rollbackDeployment");
    expect(workbench).toContain("版本差异");
    expect(workbench).toContain("必须调用");
    expect(workbench).toContain("禁止");
    expect(errorBoundary).toContain("Agent Studio 没有正常加载");
    expect(errorBoundary).toContain("重新加载");
    expect(loadingBoundary).toContain("正在恢复 Agent Studio");
    expect(styles).toContain(".studioStateShell");
    expect(styles).toContain(".deploymentControlPlane");
    expect(styles).toContain(".environmentGrid");
    expect(styles).toContain(".qualityControlPlane");
  });

  it("creates a hash-bound Preview and renders real Preflight facts", () => {
    expect(workbench).toContain("studioClient.createPreview");
    expect(workbench).toContain("studioClient.cancelPreview");
    expect(workbench).toContain("crypto.randomUUID()");
    expect(workbench).toContain('["cancelled", "failed", "expired"]');
    expect(workbench).toContain("测试身份 · Draft r");
    expect(workbench).toContain("真实 Preflight · {activePreview.preflightResult.status}");
    expect(workbench).toContain("preflightStageLabels[check.stage]");
    expect(workbench).toContain("preflightProgress(activePreview.preflightResult.checks)");
    expect(workbench).toContain("execution_profile_sandbox_provider_mismatch");
    expect(workbench).toContain("本地开发 Preview");
    expect(workbench).toContain("禁止生产发布");
    expect(workbench).toContain("workspace_artifact");
    expect(workbench).toContain("Preview · {activePreview.status}");
    expect(styles).toContain(".previewBanner");
    expect(styles).toContain(".preflightDisclosure");
  });

  it("renders only tenant API rows instead of invented live agents", () => {
    expect(sidebar).toContain("<strong>Agent Studio</strong>");
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
