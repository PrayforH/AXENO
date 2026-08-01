import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

const component = readFileSync(
  join(
    process.cwd(),
    "src/components/agent-studio/mcp-catalog-control-plane.tsx",
  ),
  "utf8",
);
const navigation = readFileSync(
  join(process.cwd(), "src/components/workspace-navigation.tsx"),
  "utf8",
);
const page = readFileSync(
  join(process.cwd(), "src/app/studio/capabilities/page.tsx"),
  "utf8",
);

describe("MCP capability catalog", () => {
  it("has a discoverable Studio navigation entry and dedicated page", () => {
    expect(navigation).toContain('href: "/studio/capabilities"');
    expect(navigation).toContain('label: "MCP"');
    expect(page).toContain("<McpCatalogControlPlane");
  });

  it("supports governed registration, impact inspection and disable", () => {
    expect(component).toContain("studioClient.upsertMcp");
    expect(component).toContain('studioClient.catalogImpact("mcp", reference)');
    expect(component).toContain("studioClient.disableMcp");
    expect(component).toContain("确认停用？");
    expect(component).toContain("目录变更采用 revision");
  });

  it("authorizes MCP access to explicit network-compatible execution profiles", () => {
    expect(component).toContain("allowedProfileIds");
    expect(component).toContain("允许在哪些 Execution Profile 中使用");
    expect(component).toContain("与 MCP 定义原子保存");
    expect(component).toContain("profile.networkAccess.includes");
    expect(component).toContain("生产授权前，请确认该 Sandbox 能访问此内网地址");
    expect(component).toContain("尚未授权 Profile");
  });

  it("discovers an address and supports multi-tool selection", () => {
    expect(component).toContain("studioClient.discoverMcp");
    expect(component).toContain("MCP_IDENTIFIER_PATTERN");
    expect(component).toContain("支持连字符和单下划线");
    expect(component).toContain("服务名可保留单下划线");
    expect(component).toContain("initialize 和 tools/list");
    expect(component).toContain("检测地址");
    expect(component).toContain("TRANSPORT_LABELS");
    expect(component).toContain("已自动识别");
    expect(component).toContain("toggleTool");
    expect(component).toContain("全选");
    expect(component).toContain("清空");
    expect(component).toContain('type="search"');
  });

  it("explains which agents need resync after the reviewed tool list changes", () => {
    expect(component).toContain("result.impact.draftIds");
    expect(component).toContain("这些智能体需要同步");
    expect(component).toContain("不会自动获得新增工具");
    expect(component).toContain("/studio/agents?draft=");
    expect(component).toContain("section=capabilities");
    expect(component).toContain("去智能体更新");
  });

  it("configures required credentials without echoing stored secret values", () => {
    expect(component).toContain("studioClient.configureMcpCredential");
    expect(component).toContain("studioClient.listMcpCredentials");
    expect(component).toContain('type="password"');
    expect(component).toContain("凭据已加密保存；为安全起见不会回显原值");
    expect(component).toContain("HARNESS_MCP_SECRET_REFERENCES_JSON");
    expect(component).not.toContain('placeholder="sk-');
  });

  it("explains tenant sharing without implying automatic agent authorization", () => {
    expect(component).toContain("工作区共享目录");
    expect(component).toContain("不会自动授权给所有智能体");
    expect(component).toContain("每个智能体都要显式绑定");
    expect(component).toContain("个人、团队或工作负载作用域");
  });
});
