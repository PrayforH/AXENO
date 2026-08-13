import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

const settings = readFileSync(join(process.cwd(), "src/app/settings/page.tsx"), "utf8");
const management = readFileSync(
  join(process.cwd(), "src/components/model-management.tsx"),
  "utf8",
);

describe("model management settings", () => {
  it("shows the control plane only to workspace administrators", () => {
    expect(settings).toContain('membership.role === "owner" || membership.role === "admin"');
    expect(settings).toContain('item.href !== "#models" || canManageModels');
    expect(settings).toContain("{canManageModels && (");
    expect(settings).toContain("<ModelManagement />");
  });

  it("supports only conversation, vision and image generation", () => {
    expect(management).toContain('type ModelType = "chat" | "vision" | "image_generation"');
    expect(management).toContain("图像生成");
    expect(management).toContain("不参与对话路由");
  });

  it("never loads or displays a stored API key", () => {
    expect(management).toContain("API Key 加密保存且不回传浏览器");
    expect(management).toContain("已安全保存；留空则保持不变");
    expect(management).not.toContain("model.apiKey");
  });
});
