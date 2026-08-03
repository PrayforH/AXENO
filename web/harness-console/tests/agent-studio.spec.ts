import { describe, expect, it } from "vitest";
import {
  DEFAULT_STUDIO_DRAFT,
  MODEL_ROUTES,
  evaluateStudioDraft,
  restoreStudioDraft,
} from "../src/lib/agent-studio";

describe("Agent Studio effective contract", () => {
  const specialists = [
    {
      alias: "researcher",
      ref: "helper-agent@1.0.0",
      responsibility: "核验事实并返回依据。",
      background: true,
    },
    {
      alias: "reviewer",
      ref: "helper-agent@1.0.0",
      responsibility: "复核结论和遗漏。",
      background: true,
    },
    {
      alias: "writer",
      ref: "helper-agent@1.0.0",
      responsibility: "整理最终交付。",
      background: true,
    },
  ];

  it("offers DeepSeek V4 models as distinct executable routes", () => {
    const flash = MODEL_ROUTES.find((item) => item.id === "deepseek-v4-flash");
    const pro = MODEL_ROUTES.find((item) => item.id === "deepseek-v4-pro");

    expect(flash?.models).toEqual(["deepseek-v4-flash"]);
    expect(pro?.models).toEqual(["deepseek-v4-pro"]);
  });

  it("uses a neutral general Lead instead of a business Agent template", () => {
    const skill = DEFAULT_STUDIO_DRAFT.skills[0];

    expect(DEFAULT_STUDIO_DRAFT.name).toBe("lead-agent");
    expect(DEFAULT_STUDIO_DRAFT.domain).toBe("general-assistant");
    expect(DEFAULT_STUDIO_DRAFT.version).toBe("1.0.0");
    expect(DEFAULT_STUDIO_DRAFT.model).toBe("deepseek-v4-pro");
    expect(DEFAULT_STUDIO_DRAFT.systemPrompt).toContain("通用任务入口");
    expect(DEFAULT_STUDIO_DRAFT.systemPrompt).not.toContain("专用舆情 MCP");
    expect(skill.name).toBe("general-task-orchestration");
    expect(skill.instructions).toContain("专用流程");
    expect(DEFAULT_STUDIO_DRAFT.mcpServers).toEqual([]);
    expect(DEFAULT_STUDIO_DRAFT.subagents).toEqual([]);
  });

  it("keeps the default Lead isolated and offline until users add capabilities", () => {
    const contract = evaluateStudioDraft(DEFAULT_STUDIO_DRAFT);

    expect(contract.ready).toBe(true);
    expect(contract.network).toBe("none");
    expect(contract.networkLabel).toBe("不联网");
    expect(contract.sandboxLabel).toBe("隔离执行 · 平台托管");
    expect(contract.risk).toBe("high");
    expect(contract.collaborationLabel).toBe("单 Agent");
    expect(contract.subagentCount).toBe(0);
  });

  it("fails closed when prompt, subagent, policy and eval coverage disagree", () => {
    const contract = evaluateStudioDraft({
      ...DEFAULT_STUDIO_DRAFT,
      systemPrompt: "Only a short prompt",
      builtinTools: [...DEFAULT_STUDIO_DRAFT.builtinTools, "Task"],
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

  it("does not treat no MCP as permission for arbitrary network", () => {
    const contract = evaluateStudioDraft({
      ...DEFAULT_STUDIO_DRAFT,
      mcpServers: [],
    });

    expect(contract.network).toBe("none");
    expect(contract.networkLabel).toBe("不联网");
  });

  it("fails closed when on-demand discovery is selected on an unreviewed route", () => {
    const unsupported = evaluateStudioDraft({
      ...DEFAULT_STUDIO_DRAFT,
      toolExposureMode: "on_demand",
    });
    const supported = evaluateStudioDraft({
      ...DEFAULT_STUDIO_DRAFT,
      modelRoute: "anthropic-official",
      toolExposureMode: "on_demand",
      requiredCapabilities: [
        ...DEFAULT_STUDIO_DRAFT.requiredCapabilities,
        "tool_search",
      ],
    });

    expect(unsupported.ready).toBe(false);
    expect(unsupported.issues).toContain("当前模型路由不支持按需工具加载");
    expect(supported.issues).not.toContain("当前模型路由不支持按需工具加载");
  });

  it("fails closed for duplicate roles and floating subagent references", () => {
    const contract = evaluateStudioDraft({
      ...DEFAULT_STUDIO_DRAFT,
      subagents: [
        specialists[0],
        {
          ...specialists[1],
          alias: specialists[0].alias,
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

  it("does not bind business or helper Sub Agents in the default template", () => {
    expect(DEFAULT_STUDIO_DRAFT.subagents).toEqual([]);
    expect(DEFAULT_STUDIO_DRAFT.builtinTools).not.toContain("Task");
  });

  it("fails closed when the Studio collaboration graph exceeds runtime limits", () => {
    const contract = evaluateStudioDraft({
      ...DEFAULT_STUDIO_DRAFT,
      subagents: specialists,
      maxSubagents: 2,
      maxConcurrentSubagents: 3,
    });

    expect(contract.ready).toBe(false);
    expect(contract.issues).toContain("当前角色数超过运行上限 2");
    expect(contract.issues).toContain("并发 Sub 上限不能高于可绑定 Sub 上限");
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
      "评测 general-readonly-task 的必需与禁止工具冲突：Bash",
    );
    expect(contract.issues).toContain(
      "评测 general-readonly-task 要求未启用工具：UnknownTool",
    );
  });

  it("migrates browser drafts saved before role and trajectory contracts existed", () => {
    const legacy = {
      ...DEFAULT_STUDIO_DRAFT,
      restoreSession: undefined,
      archiveOnComplete: undefined,
      toolExposureMode: undefined,
      builtinTools: [...DEFAULT_STUDIO_DRAFT.builtinTools, "Task"],
      policy: "production-orchestrator",
      subagents: ["helper-agent@1.0.0"],
      evalCases: DEFAULT_STUDIO_DRAFT.evalCases.map(({ expect: _expect, ...testCase }) =>
        testCase,
      ),
    };

    const restored = restoreStudioDraft(legacy);

    expect(restored).not.toBeNull();
    expect(restored?.restoreSession).toBe(true);
    expect(restored?.archiveOnComplete).toBe(true);
    expect(restored?.toolExposureMode).toBe("eager");
    expect(restored?.subagents[0]).toMatchObject({
      ref: "helper-agent@1.0.0",
      alias: "specialist-1",
    });
    expect(restored?.evalCases[0].expect.requiredTools).toEqual([]);
    expect(evaluateStudioDraft(restored as typeof DEFAULT_STUDIO_DRAFT).ready).toBe(true);
  });
});
