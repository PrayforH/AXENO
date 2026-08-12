import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

const component = readFileSync(
  join(process.cwd(), "src/components/agent-studio/mcp-catalog-control-plane.tsx"),
  "utf8",
);
const page = readFileSync(
  join(process.cwd(), "src/app/studio/knowledge/page.tsx"),
  "utf8",
);

describe("Knowledge control plane", () => {
  it("is a first-class Studio page for external knowledge only", () => {
    expect(page).toContain('<McpCatalogControlPlane mode="knowledge"');
    expect(component).toContain('active={knowledgeMode ? "knowledge" : "capabilities"}');
    expect(component).toContain("接入外部知识库");
    expect(component).toContain("文档、切片、Embedding 与向量索引均留在外部系统");
  });

  it("uses governed MCP registration and manual tool discovery", () => {
    expect(component).toContain('membership.role !== "viewer"');
    expect(component).toContain("studioClient.discoverMcp");
    expect(component).toContain("检测地址");
    expect(component).toContain("已选择 {draft.tools.length} 个");
  });

  it("keeps document processing in the external service", () => {
    expect(component).toContain("文档、切片、Embedding 与向量索引均留在外部系统");
    expect(component).toContain('category === category');
  });

  it("keeps connection definitions and credentials personal", () => {
    expect(component).toContain("个人能力目录");
    expect(component).toContain("只属于当前用户");
    expect(component).toContain("不会因共享智能体而共享");
  });
});
