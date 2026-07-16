import { describe, expect, it } from "vitest";
import {
  DEFAULT_STUDIO_DRAFT,
  evaluateStudioDraft,
} from "../src/lib/agent-studio";

describe("Agent Studio effective contract", () => {
  it("models Tavily as controlled MCP egress while keeping sandbox mandatory", () => {
    const contract = evaluateStudioDraft(DEFAULT_STUDIO_DRAFT);

    expect(contract.ready).toBe(true);
    expect(contract.network).toBe("external");
    expect(contract.networkLabel).toBe("受控外部 MCP");
    expect(contract.sandboxLabel).toBe("隔离执行 · 平台托管");
    expect(contract.risk).toBe("medium");
  });

  it("fails closed when prompt, subagent, policy and eval coverage disagree", () => {
    const contract = evaluateStudioDraft({
      ...DEFAULT_STUDIO_DRAFT,
      systemPrompt: "Only a short prompt",
      subagents: [],
      policy: "production-read-only",
      evalCases: DEFAULT_STUDIO_DRAFT.evalCases.filter(
        (testCase) => testCase.tag === "happy",
      ),
    });

    expect(contract.ready).toBe(false);
    expect(contract.issues).toContain("System Prompt 缺少必需章节");
    expect(contract.issues).toContain("Task 工具需要固定版本子 Agent");
    expect(contract.issues).toContain("只读权限不能包含写入或命令工具");
    expect(contract.issues).toContain("评测集缺少 ambiguous 场景");
    expect(contract.issues).toContain("评测集缺少 safety 场景");
  });

  it("does not treat no Tavily as permission for arbitrary network", () => {
    const contract = evaluateStudioDraft({
      ...DEFAULT_STUDIO_DRAFT,
      mcpServers: [],
    });

    expect(contract.network).toBe("none");
    expect(contract.networkLabel).toBe("不联网");
  });
});
