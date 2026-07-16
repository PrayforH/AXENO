import { describe, expect, it } from "vitest";
import {
  DEFAULT_STUDIO_DRAFT,
  evaluateStudioDraft,
  restoreStudioDraft,
} from "../src/lib/agent-studio";

describe("Agent Studio effective contract", () => {
  it("models Tavily as controlled MCP egress while keeping sandbox mandatory", () => {
    const contract = evaluateStudioDraft(DEFAULT_STUDIO_DRAFT);

    expect(contract.ready).toBe(true);
    expect(contract.network).toBe("external");
    expect(contract.networkLabel).toBe("受控外部 MCP");
    expect(contract.sandboxLabel).toBe("隔离执行 · 平台托管");
    expect(contract.risk).toBe("medium");
    expect(contract.collaborationLabel).toBe("1 Lead + 3 Sub");
    expect(contract.subagentCount).toBe(3);
    expect(contract.backgroundSubagentCount).toBe(3);
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

  it("fails closed for duplicate roles and floating subagent references", () => {
    const contract = evaluateStudioDraft({
      ...DEFAULT_STUDIO_DRAFT,
      subagents: [
        DEFAULT_STUDIO_DRAFT.subagents[0],
        {
          ...DEFAULT_STUDIO_DRAFT.subagents[1],
          alias: DEFAULT_STUDIO_DRAFT.subagents[0].alias,
          ref: "helper-agent",
        },
      ],
    });

    expect(contract.ready).toBe(false);
    expect(contract.issues).toContain("Sub Agent 角色别名不能重复");
    expect(contract.issues).toContain(
      "Sub Agent 必须固定 name@version：helper-agent",
    );
  });

  it("keeps template Sub Agent references immutable while live options come from API", () => {
    for (const agent of DEFAULT_STUDIO_DRAFT.subagents) {
      expect(agent.ref).toMatch(/^[a-z][a-z0-9-]*@[^@]+$/);
    }
  });

  it("fails closed when an eval trajectory contradicts the runtime contract", () => {
    const contract = evaluateStudioDraft({
      ...DEFAULT_STUDIO_DRAFT,
      evalCases: [
        {
          ...DEFAULT_STUDIO_DRAFT.evalCases[0],
          expect: {
            ...DEFAULT_STUDIO_DRAFT.evalCases[0].expect,
            requiredTools: ["Bash", "UnknownTool"],
            forbiddenTools: ["Bash"],
          },
        },
        ...DEFAULT_STUDIO_DRAFT.evalCases.slice(1),
      ],
    });

    expect(contract.ready).toBe(false);
    expect(contract.issues).toContain(
      "评测 evidence-backed-brief 的必需与禁止工具冲突：Bash",
    );
    expect(contract.issues).toContain(
      "评测 evidence-backed-brief 要求未启用工具：Bash, UnknownTool",
    );
  });

  it("migrates browser drafts saved before role and trajectory contracts existed", () => {
    const legacy = {
      ...DEFAULT_STUDIO_DRAFT,
      restoreSession: undefined,
      archiveOnComplete: undefined,
      subagents: ["helper-agent@1.0.0"],
      evalCases: DEFAULT_STUDIO_DRAFT.evalCases.map(({ expect: _expect, ...testCase }) =>
        testCase,
      ),
    };

    const restored = restoreStudioDraft(legacy);

    expect(restored).not.toBeNull();
    expect(restored?.restoreSession).toBe(true);
    expect(restored?.archiveOnComplete).toBe(true);
    expect(restored?.subagents[0]).toMatchObject({
      ref: "helper-agent@1.0.0",
      alias: "fact-researcher",
    });
    expect(restored?.evalCases[0].expect.requiredTools).toEqual(["Read"]);
    expect(evaluateStudioDraft(restored as typeof DEFAULT_STUDIO_DRAFT).ready).toBe(true);
  });
});
