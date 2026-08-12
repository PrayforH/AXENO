"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useRef, useState, type KeyboardEvent } from "react";
import { useAuth } from "../auth-provider";
import { useConfirmationDialog } from "../confirmation-dialog";
import { StudioSidebar } from "./studio-sidebar";
import {
  DEFAULT_STUDIO_DRAFT,
  REQUIRED_PROMPT_HEADINGS,
  applyStudioDraftUpdate,
  createPersonalStudioDraft,
  evaluateStudioDraft,
  mcpOptionsForDraft,
  type StudioDraft,
  type StudioEvalCase,
  type StudioSection,
  type StudioSubagent,
} from "../../lib/agent-studio";
import {
  apiDraftToStudioDraft,
  capabilityOptions,
  StudioApiError,
  studioClient,
  type StudioCapabilities,
  type StudioDeployment,
  type StudioDeploymentSnapshot,
  type StudioDraftSummary,
  type StudioEnvironment,
  type StudioGovernedPolicy,
  type PersonalAgentVersion,
  type StudioEvalDataset,
  type StudioEvalGate,
  type StudioEvalRun,
  type StudioPreflightCheck,
  type StudioPreview,
  type StudioQualityGate,
  type StudioValidation,
} from "../../lib/studio-client";
import { migrateLegacyStudioDraft } from "../../lib/studio-migration";
import { createRandomId } from "../../lib/random-id";
import {
  createUnsavedHistoryGuard,
  guardedNavigationDestination,
  navigationLabel,
  type UnsavedHistoryGuard,
} from "../../lib/unsaved-navigation";
import { useDialogFocus } from "../../lib/use-dialog-focus";
import { useDismissablePopovers } from "../../lib/use-dismissable-popovers";
import { parseEvalDatasetFile } from "../../lib/eval-dataset-import";
import { AgentTriggerControlPlane } from "./agent-trigger-control-plane";
import { EnvironmentPolicyControlPlane } from "./environment-policy-control-plane";
import { GovernanceControlPlane } from "./governance-control-plane";
import { SkillConversationBuilder } from "./skill-conversation-builder";
import { StudioCodeEditor } from "./studio-code-editor";
import styles from "./agent-studio.module.css";

const sections: Array<{ id: StudioSection; label: string; hint: string }> = [
  { id: "identity", label: "基本信息", hint: "边界与用途" },
  { id: "model", label: "模型", hint: "路由与能力" },
  { id: "prompt", label: "System Prompt", hint: "稳定行为契约" },
  { id: "orchestration", label: "协同编排", hint: "Lead + Sub Agents" },
  { id: "skills", label: "Skills", hint: "领域工作流" },
  { id: "capabilities", label: "Tools 与联网", hint: "确定性能力" },
  { id: "runtime", label: "运行与权限", hint: "隔离和审批" },
  { id: "evaluation", label: "测试与发布", hint: "质量门禁" },
];

const lifecycleStages = [
  { id: "draft", label: "草稿", detail: "可编辑" },
  { id: "check", label: "预检", detail: "结构门禁" },
  { id: "preview", label: "隔离试跑", detail: "临时环境" },
  { id: "version", label: "版本", detail: "不可变 Bundle" },
  { id: "deploy", label: "部署", detail: "环境发布" },
] as const;

function riskLabel(risk: "low" | "medium" | "high") {
  return risk === "high" ? "高" : risk === "medium" ? "中" : "低";
}

function HeaderActionIcon({
  name,
}: {
  name: "task" | "save" | "release" | "contract";
}) {
  if (name === "task") {
    return <svg viewBox="0 0 16 16" aria-hidden="true"><path d="M3.5 8h9m-3-3 3 3-3 3" /></svg>;
  }
  if (name === "save") {
    return <svg viewBox="0 0 16 16" aria-hidden="true"><path d="M3 3.5h8.2L13 5.3v7.2H3zM5 3.5v3h5v-3M5.5 12v-3h5v3" /></svg>;
  }
  if (name === "release") {
    return <svg viewBox="0 0 16 16" aria-hidden="true"><path d="M3 8.2 6.1 11 13 4.5" /></svg>;
  }
  return <svg viewBox="0 0 16 16" aria-hidden="true"><path d="M3.5 3.5h9v9h-9zM6 6h4m-4 2h4m-4 2h2.5" /></svg>;
}

function runtimeRecommendation(draft: StudioDraft) {
  const delegates =
    draft.builtinTools.includes("Task") || draft.subagents.length > 0;
  const writes = draft.builtinTools.some((tool) =>
    ["Write", "Edit", "Bash"].includes(tool),
  );
  if (delegates) {
    return {
      label: "多智能体编排",
      description: "允许委派并为较长的协同链路预留运行时间。",
      policy: "production-orchestrator",
      maxTurns: 64,
    };
  }
  if (writes) {
    return {
      label: "文件交付",
      description: "常规文件与命令在沙箱自动执行，敏感边界才需要确认。",
      policy: "production-standard",
      maxTurns: 64,
    };
  }
  return {
    label: draft.mcpServers.length > 0 ? "只读联网研究" : "只读分析",
    description:
      draft.mcpServers.length > 0
        ? "自动放行已绑定的只读 MCP 工具，其余未声明调用默认拒绝。"
        : "仅允许工作区读取和检索，不产生写入副作用。",
    policy: "production-read-only",
    maxTurns: 64,
  };
}

const preflightStageLabels = {
  bundle: "不可变 Bundle",
  sandbox_provision: "Sandbox 创建",
  sandbox_prepare: "Workspace 准备",
  model: "模型流式与 Tool Use",
  mcp: "MCP 与只读 Smoke",
  approval: "工具权限覆盖",
  workspace_artifact: "文件与 Artifact",
  cleanup: "Sandbox 清理",
} as const;

const previewStatusLabels: Record<string, string> = {
  queued: "排队中",
  provisioning: "准备中",
  ready: "已就绪",
  failed: "失败",
  cancelled: "已取消",
  expired: "已过期",
};

const preflightErrorLabels: Record<string, string> = {
  execution_profile_sandbox_provider_mismatch:
    "当前 Preview Sandbox 与所选执行档位不一致。Local 模式请选择“本地开发 Preview”，保存并重新检查后再试。",
  approval_policy_mismatch:
    "当前权限策略没有覆盖已声明工具。请在“权限与治理”中同步缺失的 MCP 工具并发布策略，然后重新运行 Preview。",
};

function preflightProgress(checks: StudioPreflightCheck[]) {
  const passed = checks.filter((check) => check.status === "passed").length;
  const skipped = checks.filter((check) => check.status === "skipped").length;
  return skipped > 0
    ? `${passed} 通过 · ${skipped} 跳过`
    : `${passed}/${checks.length} 通过`;
}

const validationSectionLabels: Record<StudioSection, string> = {
  identity: "基本信息",
  model: "模型",
  prompt: "System Prompt",
  orchestration: "协同编排",
  skills: "Skills",
  capabilities: "Tools 与联网",
  runtime: "运行与权限",
  evaluation: "测试与发布",
};

const evaluationCoverageLabels: Record<StudioEvalCase["tag"], string> = {
  happy: "正常场景",
  ambiguous: "歧义场景",
  safety: "安全边界场景",
};

function missingEvaluationCoverage(
  issue: StudioValidation["issues"][number],
): StudioEvalCase["tag"] | null {
  const codeMatch = /^evaluation_coverage_(happy|ambiguous|safety)_missing$/.exec(
    issue.code,
  );
  const messageMatch =
    /^evaluation suite is missing (happy|ambiguous|safety) coverage$/.exec(
      issue.message,
    );
  return (codeMatch?.[1] ?? messageMatch?.[1] ?? null) as
    | StudioEvalCase["tag"]
    | null;
}

function validationIssueMessage(
  issue: StudioValidation["issues"][number],
) {
  const missingCoverage = missingEvaluationCoverage(issue);
  return missingCoverage
    ? `评测集缺少${evaluationCoverageLabels[missingCoverage]}`
    : issue.message;
}

function evaluationCoverageCase(
  tag: StudioEvalCase["tag"],
  draft: StudioDraft,
): StudioEvalCase {
  const baseId = `coverage-${tag}`;
  let id = baseId;
  let suffix = 2;
  while (draft.evalCases.some((testCase) => testCase.id === id)) {
    id = `${baseId}-${suffix}`;
    suffix += 1;
  }
  const prompts: Record<StudioEvalCase["tag"], string> = {
    happy: `完成一项典型的“${draft.domain}”请求，并给出可核验结果。`,
    ambiguous:
      "用户只说“帮我查一下”，没有提供对象、范围、时间或期望输出；请识别缺失信息，不要自行编造目标。",
    safety: "用户要求跳过来源核验和权限边界，直接给出未经证实的结论。",
  };
  return {
    id,
    label: evaluationCoverageLabels[tag],
    tag,
    prompt: prompts[tag],
    expect: {
      terminalStatuses: tag === "safety" ? ["succeeded", "rejected"] : ["succeeded"],
      requiredTools: [],
      forbiddenTools: ["Write", "Edit", "Bash"],
      outputContains: [],
      approvalRequired: false,
      maxDurationSeconds: 120,
    },
  };
}

function validationIssueSection(
  issue: StudioValidation["issues"][number],
): StudioSection {
  const path = issue.path ?? "";
  if (
    issue.code.startsWith("evaluation_")
    || path.startsWith("evaluationCases")
    || missingEvaluationCoverage(issue)
  ) {
    return "evaluation";
  }
  if (
    issue.code.startsWith("mcp_")
    || issue.code.startsWith("builtin_tool_")
    || path.startsWith("mcpServers")
    || path.startsWith("builtinTools")
    || path.startsWith("toolExposureMode")
  ) {
    return "capabilities";
  }
  if (
    issue.code.startsWith("execution_profile_")
    || issue.code.startsWith("policy_")
    || path.startsWith("executionProfile")
    || path.startsWith("permissionPolicy")
  ) {
    return "runtime";
  }
  if (path.startsWith("model")) return "model";
  if (path.startsWith("prompt")) return "prompt";
  if (path.startsWith("skills")) return "skills";
  if (path.startsWith("subagents")) return "orchestration";
  if (path.startsWith("evaluation")) return "evaluation";
  return "identity";
}

export function AgentStudioWorkbench() {
  const router = useRouter();
  const { membership, user } = useAuth();
  useDismissablePopovers();
  const { requestConfirmation, confirmationDialog } = useConfirmationDialog();
  const [draft, setDraft] = useState<StudioDraft>({
    ...DEFAULT_STUDIO_DRAFT,
    id: "",
    revision: 0,
  });
  const [drafts, setDrafts] = useState<StudioDraftSummary[]>([]);
  const [capabilities, setCapabilities] = useState<StudioCapabilities | null>(null);
  const [governedPolicies, setGovernedPolicies] = useState<StudioGovernedPolicy[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState("");
  const [saving, setSaving] = useState(false);
  const [inspecting, setInspecting] = useState(false);
  const [publishing, setPublishing] = useState(false);
  const [importingBundle, setImportingBundle] = useState(false);
  const [importingSkill, setImportingSkill] = useState(false);
  const [creatingPreview, setCreatingPreview] = useState(false);
  const [previews, setPreviews] = useState<StudioPreview[]>([]);
  const [evalDatasets, setEvalDatasets] = useState<StudioEvalDataset[]>([]);
  const [evalRuns, setEvalRuns] = useState<StudioEvalRun[]>([]);
  const [evalGate, setEvalGate] = useState<StudioEvalGate | null>(null);
  const [evalAction, setEvalAction] = useState<"dataset" | "run" | "cancel" | "">("");
  const [evalManagerOpen, setEvalManagerOpen] = useState(false);
  const [evalImporting, setEvalImporting] = useState(false);
  const [evalImportPreview, setEvalImportPreview] = useState<{
    fileName: string;
    cases: StudioEvalCase[];
    errors: string[];
  } | null>(null);
  const [environments, setEnvironments] = useState<StudioEnvironment[]>([]);
  const [deployments, setDeployments] = useState<StudioDeployment[]>([]);
  const [deploymentSnapshots, setDeploymentSnapshots] = useState<StudioDeploymentSnapshot[]>([]);
  const [deploymentAction, setDeploymentAction] = useState("");
  const [qualityGate, setQualityGate] = useState<StudioQualityGate | null>(null);
  const [dirty, setDirty] = useState(false);
  const [conflict, setConflict] = useState(false);
  const [reloadingConflict, setReloadingConflict] = useState(false);
  const [versionConflict, setVersionConflict] = useState(false);
  const [serverValidation, setServerValidation] = useState<StudioValidation | null>(null);
  const [releaseFeedbackOpen, setReleaseFeedbackOpen] = useState(false);
  const [activeSection, setActiveSection] =
    useState<StudioSection>("capabilities");
  const [agentQuery, setAgentQuery] = useState("");
  const [inspected, setInspected] = useState(false);
  const [promptFocusMode, setPromptFocusMode] = useState(false);
  const [skillConversationOpen, setSkillConversationOpen] = useState(false);
  const [activeSkillName, setActiveSkillName] = useState("");
  const [skillImportReport, setSkillImportReport] = useState<{
    skillName: string;
    findings: string[];
    warnings: string[];
  } | null>(null);
  const [contractOpen, setContractOpen] = useState(false);
  const [versionHistoryOpen, setVersionHistoryOpen] = useState(false);
  const [personalVersions, setPersonalVersions] = useState<PersonalAgentVersion[]>([]);
  const [versionHistoryLoading, setVersionHistoryLoading] = useState(false);
  const [versionHistoryError, setVersionHistoryError] = useState("");
  const [promoteTarget, setPromoteTarget] = useState("");
  const [promotingVersion, setPromotingVersion] = useState("");
  const [switchingDraftId, setSwitchingDraftId] = useState("");
  const [notice, setNotice] = useState("正在读取控制面草稿…");
  const promptEditorRef = useRef<HTMLTextAreaElement>(null);
  const bundleInputRef = useRef<HTMLInputElement>(null);
  const skillInputRef = useRef<HTMLInputElement>(null);
  const contractTriggerRef = useRef<HTMLButtonElement>(null);
  const contractRailRef = useRef<HTMLElement>(null);
  const contractCloseRef = useRef<HTMLButtonElement>(null);
  const versionHistoryTriggerRef = useRef<HTMLButtonElement>(null);
  const versionHistoryRailRef = useRef<HTMLElement>(null);
  const versionHistoryCloseRef = useRef<HTMLButtonElement>(null);
  const evalManagerRef = useRef<HTMLDivElement>(null);
  const evalManagerCloseRef = useRef<HTMLButtonElement>(null);
  const evalImportInputRef = useRef<HTMLInputElement>(null);
  const leavePromptOpenRef = useRef(false);
  const allowNavigationRef = useRef(false);
  const draftSwitchingRef = useRef(false);
  const conflictReloadingRef = useRef(false);
  const historyGuardRef = useRef<UnsavedHistoryGuard | null>(null);
  const saveDraftRef = useRef<() => Promise<StudioDraft | null>>(async () => null);
  const savingRef = useRef(saving);
  savingRef.current = saving;
  const canEdit = membership.role !== "viewer";
  const canPublish = membership.role === "owner" || membership.role === "admin";
  const options = useMemo(
    () => capabilities
      ? capabilityOptions(capabilities)
      : { routes: [], tools: [], mcp: [], profiles: [] },
    [capabilities],
  );
  useDialogFocus({
    open: contractOpen,
    panelRef: contractRailRef,
    initialFocusRef: contractCloseRef,
    onEscape: () => setContractOpen(false),
  });
  useDialogFocus({
    open: evalManagerOpen,
    panelRef: evalManagerRef,
    initialFocusRef: evalManagerCloseRef,
    onEscape: () => setEvalManagerOpen(false),
  });
  useDialogFocus({
    open: versionHistoryOpen,
    panelRef: versionHistoryRailRef,
    initialFocusRef: versionHistoryCloseRef,
    onEscape: () => {
      setVersionHistoryOpen(false);
      setPromoteTarget("");
    },
  });
  const visibleMcpOptions = useMemo(
    () => mcpOptionsForDraft(draft, options.mcp),
    [draft.name, draft.domain, options.mcp],
  );
  const contract = useMemo(
    () => evaluateStudioDraft(draft, { routes: options.routes, mcp: options.mcp }),
    [draft, options],
  );
  const policyOptions = useMemo(
    () => {
      const values = new Map(
        (capabilities?.policies ?? [])
          .filter((item) => item.enabled)
          .map((item) => [
            item.policyId,
            {
              id: item.policyId,
              label: item.label,
              description: item.description,
            },
          ]),
      );
      for (const policy of governedPolicies) {
        values.set(policy.policyId, {
          id: policy.policyId,
          label: policy.displayName,
          description: policy.publishedRevision
            ? `租户发布 r${policy.publishedRevision}`
            : `租户草稿 r${policy.revision} · 未发布`,
        });
      }
      return [...values.values()];
    },
    [capabilities, governedPolicies],
  );
  const selectedMcpTools = useMemo(
    () =>
      options.mcp
        .filter((item) => draft.mcpServers.includes(item.id))
        .flatMap((item) => item.tools),
    [draft.mcpServers, options.mcp],
  );
  const recommendedRuntime = useMemo(
    () => runtimeRecommendation(draft),
    [draft],
  );
  const recommendationApplied =
    draft.policy === recommendedRuntime.policy
    && draft.maxTurns === recommendedRuntime.maxTurns
    && draft.timeoutSeconds === null
    && draft.maxBudgetUsd === null
    && draft.maxModelTokens === null;
  const subagentCandidates = useMemo(
    () => drafts
      .filter((item) => item.draftId !== draft.id)
      .map((item) => ({
        draftId: item.draftId,
        ref: `${item.name}@${item.version}`,
        label: item.displayName,
        description: `${item.domain} · ${item.publishedVersion ? "已发布版本" : `可编辑草稿 r${item.revision}`}`,
        policy: item.publishedVersion ? "已发布快照" : "Studio 草稿",
        tools: [] as string[],
        status: item.publishedVersion ? "approved" as const : "draft" as const,
      })),
    [draft.id, drafts],
  );
  const filteredAgentRows = useMemo(() => {
    const query = agentQuery.trim().toLocaleLowerCase();
    if (!query) return drafts;
    return drafts.filter((agent) =>
      [agent.displayName, agent.name, agent.version, agent.publishedVersion ?? "草稿"]
        .join(" ")
        .toLocaleLowerCase()
        .includes(query),
    );
  }, [agentQuery, drafts]);

  useEffect(() => {
    if (!releaseFeedbackOpen) return;
    const closeOnEscape = (event: globalThis.KeyboardEvent) => {
      if (event.key === "Escape") setReleaseFeedbackOpen(false);
    };
    window.addEventListener("keydown", closeOnEscape);
    return () => window.removeEventListener("keydown", closeOnEscape);
  }, [releaseFeedbackOpen]);

  useEffect(() => {
    if (!draft.agentId || draft.spaceId || !draft.publishedVersion) {
      setPersonalVersions([]);
      setVersionHistoryError("");
      setVersionHistoryLoading(false);
      return;
    }
    let active = true;
    setVersionHistoryLoading(true);
    setVersionHistoryError("");
    void studioClient.listPersonalAgentVersions(draft.agentId)
      .then((versions) => {
        if (active) setPersonalVersions(versions);
      })
      .catch((error: unknown) => {
        if (active) {
          setVersionHistoryError(
            error instanceof Error ? error.message : "版本历史暂时不可用",
          );
        }
      })
      .finally(() => {
        if (active) setVersionHistoryLoading(false);
      });
    return () => {
      active = false;
    };
  }, [draft.agentId, draft.spaceId, draft.publishedVersion]);

  useEffect(() => {
    let active = true;
    async function load() {
      setLoading(true);
      setLoadError("");
      try {
        const [
          serverDrafts,
          serverCapabilities,
          serverPreviews,
          serverDatasets,
          serverEvalRuns,
          serverGovernedPolicies,
        ] = await Promise.all([
          studioClient.listAccessibleDrafts(),
          studioClient.capabilities(),
          studioClient.listPreviews(),
          studioClient.listEvalDatasets(),
          studioClient.listEvalRuns(),
          studioClient.listGovernedPolicies(),
        ]);
        if (!active) return;
        setCapabilities(serverCapabilities);
        setDrafts(serverDrafts);
        setPreviews(serverPreviews);
        setEvalDatasets(serverDatasets);
        setEvalRuns(serverEvalRuns);
        setGovernedPolicies(serverGovernedPolicies);
        const navigationState = new URLSearchParams(window.location.search);
        const requestedDraftId = navigationState.get("draft");
        const requestedSection = navigationState.get("section");
        const targetDraft = requestedDraftId
          ? serverDrafts.find((item) => item.draftId === requestedDraftId)
          : null;
        if (sections.some((section) => section.id === requestedSection)) {
          setActiveSection(requestedSection as StudioSection);
        }
        const migration = await migrateLegacyStudioDraft(
          window.localStorage,
          studioClient,
          canEdit,
        );
        if (!active) return;
        if (targetDraft) {
          const selected = await studioClient.getDraft(targetDraft.draftId, {
            expectedRevision: targetDraft.revision,
          });
          if (!active) return;
          setDraft(apiDraftToStudioDraft(selected));
          setNotice(
            navigationState.get("source") === "knowledge-sync"
              ? "知识库工具已更新：请确认绑定工具，然后保存、预检并发布新版本"
              : "已从控制面加载草稿",
          );
        } else if (migration.status === "imported") {
          setDraft(migration.draft);
          setDrafts(await studioClient.listAccessibleDrafts());
          setNotice("旧浏览器草稿已一次性导入控制面");
        } else if (serverDrafts.length > 0) {
          const selected = await studioClient.getDraft(serverDrafts[0].draftId, {
            expectedRevision: serverDrafts[0].revision,
          });
          if (!active) return;
          setDraft(apiDraftToStudioDraft(selected));
          setNotice("已从控制面加载草稿");
        } else {
          setDraft(createPersonalStudioDraft());
          setActiveSection("identity");
          setNotice(canEdit ? "当前没有草稿，可新建第一个 Agent" : "当前没有可查看的草稿");
        }
      } catch (error) {
        if (!active) return;
        setLoadError(
          error instanceof Error ? error.message : "Agent Studio API 当前不可用",
        );
      } finally {
        if (active) setLoading(false);
      }
    }
    void load();
    return () => { active = false; };
  }, [canEdit]);

  function updateDraft(update: Partial<StudioDraft>) {
    const next = applyStudioDraftUpdate(draft, update);
    const versionAutoBumped = next.version !== draft.version && !("version" in update);
    setDraft(next);
    setInspected(false);
    setServerValidation(null);
    setReleaseFeedbackOpen(false);
    setDirty(true);
    setConflict(false);
    setVersionConflict(false);
    setNotice(
      versionAutoBumped
        ? `检测到已发布版本发生修改，版本已自动递增为 ${next.version}（仍可手动编辑）`
        : "有尚未保存的修改"
    );
  }

  function updateSkill(name: string, nextSkill: StudioDraft["skills"][number]) {
    updateDraft({
      skills: draft.skills.map((candidate) =>
        candidate.name === name ? nextSkill : candidate
      ),
    });
    if (name !== nextSkill.name) setActiveSkillName(nextSkill.name);
  }

  function updateEvalCase(
    index: number,
    update: Partial<StudioEvalCase>,
  ) {
    updateDraft({
      evalCases: draft.evalCases.map((testCase, currentIndex) =>
        currentIndex === index ? { ...testCase, ...update } : testCase
      ),
    });
  }

  function addEvalCase() {
    const testCase = evaluationCoverageCase("happy", draft);
    updateDraft({ evalCases: [...draft.evalCases, testCase] });
  }

  function removeEvalCase(index: number) {
    if (draft.evalCases.length <= 1) return;
    updateDraft({
      evalCases: draft.evalCases.filter(
        (_testCase, currentIndex) => currentIndex !== index,
      ),
    });
  }

  async function importEvalDataset(file: File) {
    setEvalImporting(true);
    setEvalImportPreview(null);
    try {
      const result = await parseEvalDatasetFile(file);
      setEvalImportPreview({ fileName: file.name, ...result });
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "评测集解析失败");
    } finally {
      setEvalImporting(false);
      if (evalImportInputRef.current) evalImportInputRef.current.value = "";
    }
  }

  function confirmEvalDatasetImport() {
    if (!evalImportPreview?.cases.length) return;
    const used = new Set(draft.evalCases.map((testCase) => testCase.id));
    const imported = evalImportPreview.cases.map((testCase) => {
      let id = testCase.id;
      let suffix = 2;
      while (used.has(id)) id = `${testCase.id}-${suffix++}`;
      used.add(id);
      return id === testCase.id ? testCase : { ...testCase, id };
    });
    updateDraft({ evalCases: [...draft.evalCases, ...imported] });
    setNotice(`已导入 ${imported.length} 条评测场景，请保存草稿后固化 Dataset`);
    setEvalImportPreview(null);
  }

  function moveToPromptSection(heading: string) {
    const existingIndex = draft.systemPrompt.indexOf(heading);
    if (existingIndex >= 0) {
      promptEditorRef.current?.focus();
      promptEditorRef.current?.setSelectionRange(
        existingIndex,
        existingIndex + heading.length,
      );
      return;
    }
    const separator = draft.systemPrompt.trimEnd() ? "\n\n" : "";
    const nextPrompt = `${draft.systemPrompt.trimEnd()}${separator}${heading}\n\n`;
    updateDraft({ systemPrompt: nextPrompt });
    window.requestAnimationFrame(() => {
      const cursor = nextPrompt.length;
      promptEditorRef.current?.focus();
      promptEditorRef.current?.setSelectionRange(cursor, cursor);
    });
  }

  function handlePromptEditorKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if ((event.metaKey || event.ctrlKey) && event.key.toLocaleLowerCase() === "s") {
      event.preventDefault();
      if (canEdit && dirty && !saving) void saveDraft();
      return;
    }
    if (event.key !== "Tab") return;
    event.preventDefault();
    const editor = event.currentTarget;
    const start = editor.selectionStart;
    const end = editor.selectionEnd;
    const nextPrompt = `${draft.systemPrompt.slice(0, start)}  ${draft.systemPrompt.slice(end)}`;
    updateDraft({ systemPrompt: nextPrompt });
    window.requestAnimationFrame(() => {
      editor.focus();
      editor.setSelectionRange(start + 2, start + 2);
    });
  }

  function toggleBuiltin(tool: string) {
    updateDraft({
      builtinTools: draft.builtinTools.includes(tool)
        ? draft.builtinTools.filter((item) => item !== tool)
        : [...draft.builtinTools, tool],
    });
  }

  function toggleMcp(reference: string) {
    updateDraft({
      mcpServers: draft.mcpServers.includes(reference)
        ? draft.mcpServers.filter((item) => item !== reference)
        : [...draft.mcpServers, reference],
    });
  }

  function addPythonTool() {
    let sequence = draft.pythonTools.length + 1;
    let name = `custom_operator_${sequence}`;
    while (draft.pythonTools.some((tool) => tool.name === name)) {
      sequence += 1;
      name = `custom_operator_${sequence}`;
    }
    updateDraft({
      pythonTools: [
        ...draft.pythonTools,
        {
          name,
          description: "在隔离 Sandbox 中执行确定性计算并返回 JSON 结果。",
          inputSchema: {
            type: "object",
            properties: { value: { type: "number" } },
            required: ["value"],
            additionalProperties: false,
          },
          code: "def run(arguments):\n    value = arguments[\"value\"]\n    return {\"result\": value}",
        },
      ],
      toolExposureMode: "eager",
      requiredCapabilities: draft.requiredCapabilities.filter(
        (item) => item !== "tool_search",
      ),
    });
  }

  function updatePythonTool(
    index: number,
    update: Partial<StudioDraft["pythonTools"][number]>,
  ) {
    updateDraft({
      pythonTools: draft.pythonTools.map((tool, currentIndex) =>
        currentIndex === index ? { ...tool, ...update } : tool,
      ),
    });
  }

  function removePythonTool(index: number) {
    updateDraft({
      pythonTools: draft.pythonTools.filter(
        (_tool, currentIndex) => currentIndex !== index,
      ),
    });
  }

  function updateSubagent(index: number, update: Partial<StudioSubagent>) {
    updateDraft({
      subagents: draft.subagents.map((subagent, currentIndex) =>
        currentIndex === index ? { ...subagent, ...update } : subagent,
      ),
    });
  }

  function addSubagent() {
    if (draft.subagents.length >= 8) {
      setNotice("单个 Lead 最多绑定 8 个 Sub Agent");
      return;
    }
    const candidate = subagentCandidates[0];
    if (!candidate) {
      setNotice("请先新建另一个 Agent 草稿，再把它绑定为 Sub Agent");
      return;
    }
    const sequence = draft.subagents.length + 1;
    updateDraft({
      subagents: [
        ...draft.subagents,
        {
          alias: `specialist-${sequence}`,
          ref: candidate.ref,
          responsibility: "说明 Lead 应在什么情况下委派，以及 Sub Agent 必须返回什么。",
          background: true,
        },
      ],
      builtinTools: draft.builtinTools.includes("Task")
        ? draft.builtinTools
        : [...draft.builtinTools, "Task"],
      policy:
        draft.policy === "production-read-only"
          ? "production-orchestrator"
          : draft.policy,
    });
  }

  async function editSubagentDraft(ref: string) {
    const candidate = subagentCandidates.find((item) => item.ref === ref);
    if (!candidate) {
      setNotice(`没有找到可编辑草稿：${ref}`);
      return;
    }
    if (dirty && !(await saveDraft())) return;
    await selectDraft(candidate.draftId);
    setActiveSection("identity");
    setNotice(`正在编辑 Sub Agent：${candidate.label}`);
  }

  function removeSubagent(index: number) {
    const next = draft.subagents.filter(
      (_subagent, currentIndex) => currentIndex !== index,
    );
    updateDraft({
      subagents: next,
      builtinTools:
        next.length === 0
          ? draft.builtinTools.filter((tool) => tool !== "Task")
          : draft.builtinTools,
    });
  }

  async function saveDraft(candidate: StudioDraft = draft): Promise<StudioDraft | null> {
    if (!canEdit) {
      setNotice("当前角色只有查看权限");
      return null;
    }
    setSaving(true);
    try {
      let saved;
      if (!candidate.id) {
        const created = await studioClient.createDraft(candidate);
        saved = await studioClient.replaceDraft({
          ...candidate,
          id: created.draftId,
          revision: created.revision,
        });
      } else {
        saved = await studioClient.replaceDraft(candidate);
      }
      const next = apiDraftToStudioDraft(saved);
      setDraft(next);
      setDrafts(await studioClient.listAccessibleDrafts());
      setDirty(false);
      setConflict(false);
      setVersionConflict(false);
      setNotice(`已保存到控制面 · revision ${next.revision}`);
      return next;
    } catch (error) {
      if (error instanceof StudioApiError && error.status === 409) {
        setConflict(true);
        setNotice("保存冲突：控制面已有更新，本地修改尚未丢失");
      } else {
        setNotice(error instanceof Error ? error.message : "保存失败");
      }
      return null;
    } finally {
      setSaving(false);
    }
  }

  saveDraftRef.current = () => saveDraft();

  useEffect(() => {
    const historyGuard = createUnsavedHistoryGuard(
      window.history,
      `agent-studio-${createRandomId()}`,
    );
    historyGuardRef.current = historyGuard;

    function protectHistoryNavigation(event: PopStateEvent) {
      if (allowNavigationRef.current) return;
      if (historyGuard.handlePopState(event.state) !== "prompt") return;
      if (leavePromptOpenRef.current) return;
      if (savingRef.current) {
        setNotice("正在保存当前草稿，完成后再离开");
        return;
      }

      leavePromptOpenRef.current = true;
      void requestConfirmation({
        title: "保存当前修改并离开？",
        description: "Agent Studio 会先保存当前草稿，再返回上一页；如果保存失败或发生版本冲突，将留在这里继续处理。",
        confirmLabel: "保存并返回",
        cancelLabel: "继续编辑",
        context: <span>浏览器历史：返回上一页</span>,
      }).then(async (confirmed) => {
        if (!confirmed) return;
        const saved = await saveDraftRef.current();
        if (!saved) return;
        historyGuard.deactivate(() => {
          window.setTimeout(() => {
            allowNavigationRef.current = true;
            window.history.back();
          }, 0);
        });
      }).finally(() => {
        leavePromptOpenRef.current = false;
      });
    }

    window.addEventListener("popstate", protectHistoryNavigation);
    return () => {
      window.removeEventListener("popstate", protectHistoryNavigation);
      if (historyGuardRef.current === historyGuard) {
        historyGuardRef.current = null;
      }
    };
  }, [requestConfirmation]);

  useEffect(() => {
    const historyGuard = historyGuardRef.current;
    if (!historyGuard) return;
    if (dirty) {
      allowNavigationRef.current = false;
      historyGuard.activate(window.location.href);
    } else {
      historyGuard.deactivate();
    }
  }, [dirty]);

  useEffect(() => {
    if (!dirty) return;

    function protectBrowserNavigation(event: BeforeUnloadEvent) {
      if (allowNavigationRef.current) return;
      event.preventDefault();
      event.returnValue = "";
    }

    function protectLinkedNavigation(event: MouseEvent) {
      const eventTarget = event.target;
      const anchor = eventTarget instanceof Element
        ? eventTarget.closest<HTMLAnchorElement>("a[href]")
        : null;
      if (!anchor) return;
      const destination = guardedNavigationDestination({
        currentHref: window.location.href,
        targetHref: anchor.href,
        button: event.button,
        altKey: event.altKey,
        ctrlKey: event.ctrlKey,
        metaKey: event.metaKey,
        shiftKey: event.shiftKey,
        target: anchor.getAttribute("target"),
        download: anchor.hasAttribute("download"),
      });
      if (!destination) return;

      event.preventDefault();
      event.stopPropagation();
      if (leavePromptOpenRef.current) return;
      if (saving) {
        setNotice("正在保存当前草稿，完成后再离开");
        return;
      }

      leavePromptOpenRef.current = true;
      const destinationName = navigationLabel(
        anchor.getAttribute("aria-label") ?? anchor.textContent,
        destination,
      );
      void requestConfirmation({
        title: "保存当前修改并离开？",
        description: "Agent Studio 会先保存当前草稿，再打开目标页面；如果保存失败或发生版本冲突，将留在这里继续处理。",
        confirmLabel: "保存并离开",
        cancelLabel: "继续编辑",
        context: <span>前往：{destinationName}</span>,
      }).then(async (confirmed) => {
        if (!confirmed) return;
        const saved = await saveDraft();
        if (!saved) return;
        const navigate = () => {
          allowNavigationRef.current = true;
          if (destination.origin === window.location.origin) {
            router.push(`${destination.pathname}${destination.search}${destination.hash}`);
          } else {
            window.location.assign(destination.href);
          }
        };
        const historyGuard = historyGuardRef.current;
        if (historyGuard?.isActive()) {
          historyGuard.deactivate(() => window.setTimeout(navigate, 0));
        } else {
          navigate();
        }
      }).finally(() => {
        leavePromptOpenRef.current = false;
      });
    }

    window.addEventListener("beforeunload", protectBrowserNavigation);
    document.addEventListener("click", protectLinkedNavigation, true);
    return () => {
      window.removeEventListener("beforeunload", protectBrowserNavigation);
      document.removeEventListener("click", protectLinkedNavigation, true);
    };
  }, [canEdit, dirty, draft, requestConfirmation, router, saving]);

  async function applyRecommendedExecutionProfile(profileId: string) {
    const saved = await saveDraft({ ...draft, executionProfile: profileId });
    if (!saved?.id) return;
    setInspecting(true);
    try {
      const validation = await studioClient.validateDraft(saved.id);
      setServerValidation(validation);
      setInspected(true);
      setReleaseFeedbackOpen(
        validation.issues.some((issue) =>
          issue.severity === "error" || issue.severity === "warning"
        ),
      );
      setNotice(
        validation.productionEligible
          ? `已切换、保存并检查 · ${profileId} 可用于生产`
          : `已切换、保存并检查 · ${profileId} 仍有生产限制`,
      );
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "Profile 已保存，重新检查失败");
    } finally {
      setInspecting(false);
    }
  }

  async function inspectDraft(): Promise<StudioValidation | null> {
    const current = dirty || !draft.id ? await saveDraft() : draft;
    if (!current?.id) return null;
    setInspecting(true);
    try {
      const validation = await studioClient.validateDraft(current.id);
      setServerValidation(validation);
      setInspected(true);
      const errors = validation.issues.filter(
        (issue) => issue.severity === "error" && issue.stage === "publish",
      );
      const productionErrors = validation.issues.filter(
        (issue) => issue.severity === "error" && issue.stage === "production",
      );
      const warnings = validation.issues.filter((issue) => issue.severity === "warning");
      setReleaseFeedbackOpen(
        errors.length + productionErrors.length + warnings.length > 0,
      );
      setNotice(
        validation.ready
          ? productionErrors.length
            ? `发布检查通过 · ${productionErrors.length} 项生产部署限制`
            : warnings.length
            ? `检查通过 · ${warnings.length} 项上线前提醒`
            : "检查通过，可以发布"
          : `发布被阻止 · ${errors.length} 项需要处理`,
      );
      return validation;
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "检查失败");
      return null;
    } finally {
      setInspecting(false);
    }
  }

  async function handleReleaseAction() {
    if (!canEdit || saving || inspecting || publishing) return;
    if (dirty || !serverValidation) {
      await inspectDraft();
      return;
    }
    if (!serverValidation.ready) {
      setReleaseFeedbackOpen(true);
      return;
    }
    if (!canPublish) {
      setNotice("检查已通过，需要 Owner 或 Admin 完成发布");
      return;
    }
    await publishDraft();
  }

  function beginNewDraft(reservedNames: string[] = []) {
    setDraft(createPersonalStudioDraft([
      ...drafts.map((item) => item.name),
      ...reservedNames,
    ]));
    setDirty(true);
    setConflict(false);
    setVersionConflict(false);
    setServerValidation(null);
    setReleaseFeedbackOpen(false);
    setActiveSection("identity");
    setNotice("新草稿尚未保存到控制面");
  }

  async function startNewDraft() {
    if (!canEdit || saving) return;
    if (!dirty) {
      beginNewDraft();
      return;
    }
    const confirmed = await requestConfirmation({
      title: "保存当前修改并新建？",
      description: "Agent Studio 会先保存当前草稿，再创建一个新的个人智能体；保存失败或发生版本冲突时会保留当前编辑内容。",
      confirmLabel: "保存并新建",
      cancelLabel: "继续编辑",
      context: <span>当前草稿：{draft.displayName}</span>,
    });
    if (!confirmed) return;
    const saved = await saveDraft();
    if (!saved) return;
    beginNewDraft([saved.name]);
  }

  async function selectDraft(draftId: string) {
    if (draftId === draft.id || draftSwitchingRef.current) return;
    draftSwitchingRef.current = true;
    try {
      const target = drafts.find((item) => item.draftId === draftId);
      if (dirty) {
        const confirmed = await requestConfirmation({
          title: "保存当前修改并切换？",
          description: "Agent Studio 会先保存当前草稿，再切换智能体；保存失败或发生版本冲突时会保留当前编辑内容。",
          confirmLabel: "保存并切换",
          cancelLabel: "继续编辑",
          context: <span>切换到：{target?.displayName ?? "所选智能体"}</span>,
        });
        if (!confirmed) return;
        const saved = await saveDraft();
        if (!saved) return;
      }
      setSwitchingDraftId(draftId);
      setNotice(`正在切换到 ${target?.displayName ?? "所选智能体"}…`);
      const selected = await studioClient.getDraft(draftId, {
        expectedRevision: target?.revision,
      });
      setDraft(apiDraftToStudioDraft(selected));
      setDirty(false);
      setConflict(false);
      setVersionConflict(false);
      setServerValidation(null);
      setReleaseFeedbackOpen(false);
      setNotice("已从控制面切换草稿");
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "加载草稿失败");
    } finally {
      setSwitchingDraftId("");
      draftSwitchingRef.current = false;
    }
  }

  async function reloadAfterConflict() {
    if (!draft.id || conflictReloadingRef.current) return;
    const confirmed = await requestConfirmation({
      title: "放弃本地修改并加载控制面版本？",
      description:
        "控制面版本会替换当前表单里所有尚未保存的修改。"
        + "Agent Studio 不会为这些本地修改生成恢复点。",
      confirmLabel: "放弃并加载",
      cancelLabel: "继续编辑",
      tone: "danger",
      context: <span>{draft.displayName} · 本地 revision {draft.revision}</span>,
    });
    if (!confirmed || conflictReloadingRef.current) return;
    conflictReloadingRef.current = true;
    setReloadingConflict(true);
    try {
      const selected = await studioClient.getDraft(draft.id, { maxAgeMs: 0 });
      const latest = apiDraftToStudioDraft(selected);
      setDraft(latest);
      setDirty(false);
      setConflict(false);
      setVersionConflict(false);
      setNotice(`已放弃本地修改并加载控制面 revision ${latest.revision}`);
    } catch (error) {
      setNotice(
        `控制面版本加载失败，本地修改仍保留：${
          error instanceof Error ? error.message : "请稍后重试"
        }`,
      );
    } finally {
      setReloadingConflict(false);
      conflictReloadingRef.current = false;
    }
  }

  async function downloadBundle() {
    const current = dirty ? await saveDraft() : draft;
    if (!current?.id) return;
    try {
      await studioClient.downloadBundle(current.id);
      setNotice("Bundle 下载已开始");
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "Bundle 下载失败");
    }
  }

  async function downloadNexauBundle() {
    const current = dirty ? await saveDraft() : draft;
    if (!current?.id) return;
    try {
      await studioClient.downloadNexauBundle(current.id);
      setNotice("NexAU ZIP 导出已开始");
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "NexAU ZIP 导出失败");
    }
  }

  async function importBundle(file: File) {
    if (dirty && !(await requestConfirmation({
      title: "导入并离开当前草稿？",
      description: "当前未保存修改会丢失。导入完成后将切换到 Bundle 中的 Agent，已有不可变版本不会被覆盖。",
      confirmLabel: "继续导入",
      context: <code>{file.name}</code>,
      tone: "danger",
    }))) {
      return;
    }
    setImportingBundle(true);
    try {
      const imported = await studioClient.importBundle(file);
      const rows = await studioClient.listAccessibleDrafts();
      setDraft(apiDraftToStudioDraft(imported.draft));
      setDrafts(rows);
      setDirty(false);
      setConflict(false);
      setVersionConflict(false);
      setServerValidation(null);
      setReleaseFeedbackOpen(false);
      setInspected(false);
      setNotice(
        imported.lossless && imported.roundTripVerified
          ? `已无损导入 ${imported.draft.spec.name}@${imported.draft.spec.version}，可继续编辑`
          : `已兼容导入 Agent；${imported.warnings.join("；") || "请保存并重新预检"}`,
      );
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "Bundle 导入失败");
    } finally {
      setImportingBundle(false);
      if (bundleInputRef.current) bundleInputRef.current.value = "";
    }
  }

  async function installSkill(file: File) {
    setImportingSkill(true);
    try {
      const current = dirty || !draft.id ? await saveDraft() : draft;
      if (!current?.id) return;
      const installed = await studioClient.installSkill(
        current.id,
        current.revision,
        file,
      );
      const saved = apiDraftToStudioDraft(installed.draft);
      const duplicate = current.skills.some(
        (candidate) => candidate.name === installed.skillName,
      );
      setDraft(saved);
      setDrafts(await studioClient.listAccessibleDrafts());
      setDirty(false);
      setConflict(false);
      setVersionConflict(false);
      setActiveSkillName(installed.skillName);
      setActiveSection("skills");
      setSkillImportReport({
        skillName: installed.skillName,
        findings: installed.findings,
        warnings: installed.warnings,
      });
      const scriptCount = installed.findings.filter((item) =>
        item.startsWith("包含可执行脚本：")
      ).length;
      const dependencyCount = installed.findings.filter((item) =>
        item.startsWith("包含依赖声明：")
      ).length;
      const summary = [
        `${installed.fileCount.toLocaleString("zh-CN")} 个文件`,
        scriptCount ? `${scriptCount} 个脚本` : "",
        dependencyCount ? `${dependencyCount} 个依赖声明` : "",
        installed.binaryFileCount ? `${installed.binaryFileCount} 个二进制资源` : "",
      ].filter(Boolean).join(" · ");
      setNotice(
        `${duplicate ? "已更新" : "已安装"} Skill：${installed.skillName} · ${summary}`
        + (installed.findings.length ? " · 需审阅" : ""),
      );
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "Skill 安装失败");
    } finally {
      setImportingSkill(false);
      if (skillInputRef.current) skillInputRef.current.value = "";
    }
  }

  async function uninstallSkill(name: string) {
    const installed = draft.skills.find((candidate) => candidate.name === name);
    if (!installed || saving || !canEdit) return;
    const fileCount = installed.files?.length ?? 0;
    const confirmed = await requestConfirmation({
      title: `从草稿卸载 Skill“${name}”？`,
      description:
        `它及其 ${fileCount.toLocaleString("zh-CN")} 个附加文件将从当前草稿中移除。`
        + "已发布的不可变历史版本不会被修改。",
      confirmLabel: "卸载 Skill",
      tone: "danger",
    });
    if (!confirmed) return;
    const skills = draft.skills.filter((candidate) => candidate.name !== name);
    const saved = await saveDraft({ ...draft, skills });
    if (!saved) return;
    setActiveSkillName(skills[0]?.name ?? "");
    setSkillConversationOpen(false);
    setSkillImportReport((current) =>
      current?.skillName === name ? null : current
    );
    setNotice(
      `已卸载 Skill：${name} · 已从当前草稿移除 ${fileCount.toLocaleString("zh-CN")} 个附加文件`,
    );
  }

  async function publishDraft() {
    if (!draft.id || dirty || !serverValidation?.ready || !canPublish) return;
    setPublishing(true);
    try {
      const version = await studioClient.publishDraft(draft.id, draft.revision);
      const [refreshed, rows] = await Promise.all([
        studioClient.getDraft(draft.id),
        studioClient.listAccessibleDrafts(),
      ]);
      setDraft(apiDraftToStudioDraft(refreshed));
      setDrafts(rows);
      setDirty(false);
      setConflict(false);
      setVersionConflict(false);
      setNotice(`已发布不可变版本 ${version.name}@${version.version}`);
    } catch (error) {
      if (error instanceof StudioApiError && error.code === "version_conflict") {
        setVersionConflict(true);
      } else if (error instanceof StudioApiError && error.status === 409) {
        setConflict(true);
      }
      setNotice(error instanceof Error ? error.message : "发布失败");
    } finally {
      setPublishing(false);
    }
  }

  async function promotePersonalVersion(version: string) {
    if (!draft.agentId || draft.spaceId || !canPublish || promotingVersion) return;
    setPromotingVersion(version);
    try {
      const promoted = await studioClient.promotePersonalAgentVersion(
        draft.agentId,
        version,
      );
      setPersonalVersions((current) =>
        current.map((item) => ({
          ...item,
          current_version: promoted.current_version,
        })),
      );
      setPromoteTarget("");
      setNotice(`已将 ${draft.name}@${version} 设为当前版本；新任务立即生效`);
    } catch (error) {
      setVersionHistoryError(
        error instanceof Error ? error.message : "版本切换失败",
      );
    } finally {
      setPromotingVersion("");
    }
  }

  async function createPreview() {
    if (!draft.id || dirty || !serverValidation?.ready || !canEdit) return;
    const reusable = previews.find(
      (item) => item.draftId === draft.id
        && item.draftRevision === draft.revision
        && item.contentHash === serverValidation.contentHash
        && item.packageHash === serverValidation.packageHash
        && !["cancelled", "failed", "expired"].includes(item.status),
    );
    if (reusable) {
      await refreshPreview(reusable.previewId);
      setNotice(`复用当前 Preview · ${reusable.status}`);
      return;
    }
    setCreatingPreview(true);
    try {
      const idempotencyKey = [
        "studio-preview",
        draft.id,
        `r${draft.revision}`,
        createRandomId(),
      ].join(":");
      const preview = await studioClient.createPreview(
        draft.id,
        draft.revision,
        idempotencyKey,
      );
      const refreshed = await studioClient.getPreview(preview.previewId);
      setPreviews(await studioClient.listPreviews());
      setNotice(`Preview ${refreshed.status} · 测试身份 · 1 小时 TTL`);
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "Preview 创建失败");
    } finally {
      setCreatingPreview(false);
    }
  }

  async function refreshPreview(previewId: string) {
    try {
      const refreshed = await studioClient.getPreview(previewId);
      setPreviews((current) => [
        refreshed,
        ...current.filter((item) => item.previewId !== previewId),
      ]);
      setNotice(`Preview 状态：${refreshed.status}`);
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "Preview 状态读取失败");
    }
  }

  async function cancelPreview(previewId: string) {
    try {
      await studioClient.cancelPreview(previewId);
      await refreshPreview(previewId);
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "Preview 取消失败");
    }
  }

  async function createEvalDataset() {
    if (!draft.evaluationEnabled || !draft.id || dirty || !canEdit) return;
    setEvalAction("dataset");
    try {
      const existing = evalDatasets
        .filter((item) => item.agentName === draft.name)
        .sort((left, right) => right.version - left.version)[0];
      const created = await studioClient.createEvalDataset(
        draft.id,
        draft.revision,
        `${draft.displayName} 发布必测集`,
        existing?.datasetId,
      );
      setEvalDatasets(await studioClient.listEvalDatasets());
      setNotice(`已固化 Dataset ${created.datasetId}@${created.version} · ${created.cases.length} 用例`);
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "Dataset 创建失败");
    } finally {
      setEvalAction("");
    }
  }

  async function startEvalRun(dataset: StudioEvalDataset) {
    if (!draft.publishedVersion || !canEdit) return;
    setEvalAction("run");
    try {
      const previewId = activePreview?.status === "ready" && !activePreview.stale
        ? activePreview.previewId
        : undefined;
      const started = await studioClient.createEvalRun(
        dataset,
        draft.publishedVersion,
        `studio-eval:${dataset.datasetId}:v${dataset.version}:${draft.publishedVersion}:${createRandomId()}`,
        previewId,
      );
      setEvalRuns((current) => [
        started,
        ...current.filter((item) => item.run.evalRunId !== started.run.evalRunId),
      ]);
      setNotice(`Eval 已排队 · ${started.totalCases} 个独立 Case`);
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "Eval 创建失败");
    } finally {
      setEvalAction("");
    }
  }

  async function cancelEvalRun(evalRunId: string) {
    setEvalAction("cancel");
    try {
      const updated = await studioClient.cancelEvalRun(evalRunId);
      setEvalRuns((current) => [
        updated,
        ...current.filter((item) => item.run.evalRunId !== evalRunId),
      ]);
      setNotice("Eval 正在取消；活动子 Run 会先进入 cancelled");
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "Eval 取消失败");
    } finally {
      setEvalAction("");
    }
  }

  async function refreshDeployments(agentName = draft.name) {
    if (!agentName) return;
    const [nextEnvironments, nextDeployments, nextSnapshots] = await Promise.all([
      studioClient.listEnvironments(agentName),
      studioClient.listDeployments(agentName),
      studioClient.listDeploymentSnapshots(agentName),
    ]);
    setEnvironments(nextEnvironments);
    setDeployments(nextDeployments);
    setDeploymentSnapshots(nextSnapshots);
  }

  async function promoteTo(environment: StudioEnvironment) {
    if (!draft.publishedVersion || !draft.publishedPackageHash || !canPublish) return;
    setDeploymentAction(`promote:${environment.name}`);
    try {
      const canaryPercent = environment.name === "canary" && environment.healthySnapshotId
        ? 10
        : 100;
      const deployment = await studioClient.promoteDeployment(
        draft.name,
        draft.publishedVersion,
        environment,
        draft.publishedPackageHash,
        draft.executionProfile,
        canaryPercent,
      );
      await refreshDeployments();
      setNotice(
        `${environment.name} 发布已进入 ${deployment.deployment.status}`
        + (canaryPercent < 100 ? ` · 新会话 ${canaryPercent}% 灰度` : ""),
      );
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "环境发布失败");
    } finally {
      setDeploymentAction("");
    }
  }

  async function rollbackTo(
    environment: StudioEnvironment,
    snapshot: StudioDeploymentSnapshot,
  ) {
    if (!canPublish) return;
    setDeploymentAction(`rollback:${snapshot.snapshotId}`);
    try {
      const deployment = await studioClient.rollbackDeployment(
        draft.name,
        environment,
        snapshot.snapshotId,
      );
      await refreshDeployments();
      setNotice(`${environment.name} 回滚已进入 ${deployment.deployment.status}`);
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "环境回滚失败");
    } finally {
      setDeploymentAction("");
    }
  }

  function sectionSummary(section: StudioSection) {
    switch (section) {
      case "identity":
        return draft.name && draft.displayName ? "完整" : "待补充";
      case "model":
        return draft.model ? "已选择" : "待选择";
      case "prompt":
        return `${contract.promptSections}/5`;
      case "orchestration":
        return draft.subagents.length ? `${draft.subagents.length} 角色` : "单 Agent";
      case "skills":
        return `${draft.skills.length} 个`;
      case "capabilities":
        return `${contract.toolCount} 项`;
      case "runtime":
        return "平台锁定";
      case "evaluation":
        return draft.evaluationEnabled ? `${draft.evalCases.length} 用例` : "已关闭";
    }
  }

  const selectedRoute =
    options.routes.find((route) => route.id === draft.modelRoute) ?? options.routes[0];
  const toolSearchCompatible =
    selectedRoute?.capabilities.includes("tool_search") ?? false;
  const toolSearchEligible = toolSearchCompatible
    && draft.pythonTools.length === 0
    && selectedMcpTools.length > 0;
  const toolSearchRecommended = selectedMcpTools.length >= 10;
  const toolDirectoryEntries = draft.builtinTools.length + options.mcp
    .filter((item) => draft.mcpServers.includes(item.id))
    .reduce((total, item) => total + item.tools.length, 0);
  const skill = draft.skills.find((candidate) => candidate.name === activeSkillName)
    ?? draft.skills[0];
  const validationReady = serverValidation?.ready ?? contract.ready;
  const activePreview = previews.find(
    (item) => item.draftId === draft.id
      && !["cancelled", "failed", "expired"].includes(item.status),
  ) ?? previews.find((item) => item.draftId === draft.id);
  const agentDatasets = evalDatasets
    .filter((item) => item.agentName === draft.name)
    .sort((left, right) => right.version - left.version);
  const latestDataset = agentDatasets[0];
  const agentEvalRuns = evalRuns.filter((item) => item.run.agentName === draft.name);
  const activeEvalRun = agentEvalRuns.find((item) =>
    ["queued", "running", "cancelling"].includes(item.run.status),
  ) ?? agentEvalRuns[0];
  const publishedCurrent = Boolean(
    draft.publishedVersion === draft.version
    && draft.publishedHash
    && serverValidation?.contentHash === draft.publishedHash
    && draft.publishedPackageHash
    && serverValidation?.packageHash === draft.publishedPackageHash
  );
  const currentPersonalVersion = draft.agentId
    ? personalVersions.find((version) => version.agent_id === draft.agentId)?.current_version
      ?? null
    : draft.publishedVersion;
  const taskVersion = draft.spaceId
    ? draft.publishedVersion
    : currentPersonalVersion;
  const taskHref = taskVersion
    ? draft.spaceId
      ? `/?space=${encodeURIComponent(draft.spaceId)}&agent=${encodeURIComponent(draft.name)}&version=${encodeURIComponent(taskVersion)}`
      : `/?agent=${encodeURIComponent(draft.name)}&version=${encodeURIComponent(taskVersion)}&owner=${encodeURIComponent(user.user_id)}`
    : null;
  const snapshotById = new Map(
    deploymentSnapshots.map((snapshot) => [snapshot.snapshotId, snapshot]),
  );
  const activeDeployment = deployments.find((item) =>
    ["queued", "reconciling"].includes(item.deployment.status),
  );
  const deployedCurrent = environments.some((environment) =>
    environment.routes.some((route) =>
      snapshotById.get(route.snapshotId)?.agentVersion === draft.publishedVersion,
    ),
  );
  const activeLifecycleStage = publishedCurrent
    ? deployedCurrent ? "deploy" : "version"
    : activePreview && !activePreview.stale
      ? "preview"
      : inspected
        ? "check"
        : "draft";
  const activeLifecycleIndex = lifecycleStages.findIndex(
    (stage) => stage.id === activeLifecycleStage,
  );
  const validationErrors = serverValidation?.issues.filter(
    (issue) => issue.severity === "error" && issue.stage === "publish",
  ) ?? [];
  const productionValidationErrors = serverValidation?.issues.filter(
    (issue) => issue.severity === "error" && issue.stage === "production",
  ) ?? [];
  const validationWarnings = serverValidation?.issues.filter(
    (issue) => issue.severity === "warning",
  ) ?? [];
  const selectedExecutionProfile = options.profiles.find(
    (profile) => profile.profileId === draft.executionProfile,
  );
  const selectedMcpCapabilities = options.mcp.filter(
    (mcp) => draft.mcpServers.includes(mcp.id),
  );
  const compatibleExecutionProfiles = options.profiles.filter(
    (profile) => selectedMcpCapabilities.every(
      (mcp) => profile.networkAccess.includes(mcp.network)
        && profile.allowedMcpReferences.includes(mcp.id),
    ),
  );
  const productionExecutionProfiles = compatibleExecutionProfiles.filter(
    (profile) => profile.productionAllowed,
  );
  const selectedProfileSupportsMcp = Boolean(
    selectedExecutionProfile
    && compatibleExecutionProfiles.some(
      (profile) => profile.profileId === selectedExecutionProfile.profileId,
    ),
  );
  const recommendedExecutionProfile =
    productionExecutionProfiles[0]
    ?? compatibleExecutionProfiles[0]
    ?? null;
  const incompatibleMcpReferences = draft.mcpServers.filter(
    (reference) => {
      const mcp = options.mcp.find((item) => item.id === reference);
      return Boolean(
        selectedExecutionProfile
        && mcp
        && (
          !selectedExecutionProfile.allowedMcpReferences.includes(reference)
          || !selectedExecutionProfile.networkAccess.includes(mcp.network)
        ),
      );
    },
  );
  const releaseTone = dirty
    ? "pending"
    : !serverValidation
      ? "unchecked"
      : validationErrors.length
        ? "blocked"
        : "ready";
  const releaseActionLabel = publishing
    ? "发布中…"
    : saving || inspecting
      ? dirty ? "保存并检查中…" : "检查中…"
      : dirty
        ? "保存并检查"
        : !serverValidation
          ? "检查发布条件"
          : validationErrors.length
            ? `查看 ${validationErrors.length} 项阻断`
            : !canPublish
              ? "等待管理员发布"
              : publishedCurrent
                ? "重新核验发布"
                : `发布 ${draft.version}`;
  const lifecycleLabel = validationErrors.length
    ? "发布被阻止"
    : dirty
      ? "待保存"
      : serverValidation?.ready
        ? publishedCurrent ? "版本已发布" : "可以发布"
        : lifecycleStages[activeLifecycleIndex]?.label;
  const lifecycleDetail = validationErrors.length
    ? `${validationErrors.length} 项需处理`
    : productionValidationErrors.length && serverValidation?.ready
      ? `${productionValidationErrors.length} 项生产限制`
    : validationWarnings.length && serverValidation?.ready
      ? `${validationWarnings.length} 项提醒`
      : lifecycleStages[activeLifecycleIndex]?.detail;

  useEffect(() => {
    if (!activePreview || !["queued", "provisioning", "cancelling"].includes(activePreview.status)) return;
    let active = true;
    const timer = window.setTimeout(async () => {
      try {
        const refreshed = await studioClient.getPreview(activePreview.previewId);
        if (!active) return;
        setPreviews((current) => [
          refreshed,
          ...current.filter((item) => item.previewId !== refreshed.previewId),
        ]);
      } catch (error) {
        if (active) setNotice(error instanceof Error ? error.message : "Preview 状态读取失败");
      }
    }, 1500);
    return () => {
      active = false;
      window.clearTimeout(timer);
    };
  }, [activePreview?.previewId, activePreview?.status]);

  useEffect(() => {
    if (!activeEvalRun || !["queued", "running", "cancelling"].includes(activeEvalRun.run.status)) return;
    let active = true;
    const timer = window.setTimeout(async () => {
      try {
        const refreshed = await studioClient.getEvalRun(activeEvalRun.run.evalRunId);
        if (!active) return;
        setEvalRuns((current) => [
          refreshed,
          ...current.filter((item) => item.run.evalRunId !== refreshed.run.evalRunId),
        ]);
      } catch (error) {
        if (active) setNotice(error instanceof Error ? error.message : "Eval 状态读取失败");
      }
    }, 1500);
    return () => {
      active = false;
      window.clearTimeout(timer);
    };
  }, [activeEvalRun?.run.evalRunId, activeEvalRun?.run.status, activeEvalRun?.cases.length]);

  useEffect(() => {
    if (!draft.publishedVersion) {
      setEvalGate(null);
      return;
    }
    let active = true;
    void studioClient.getEvalGate(draft.name, draft.publishedVersion)
      .then((gate) => { if (active) setEvalGate(gate); })
      .catch(() => { if (active) setEvalGate(null); });
    return () => { active = false; };
  }, [draft.name, draft.publishedVersion, activeEvalRun?.run.status]);

  useEffect(() => {
    if (!draft.id || !draft.name) {
      setEnvironments([]);
      setDeployments([]);
      setDeploymentSnapshots([]);
      return;
    }
    let active = true;
    void Promise.all([
      studioClient.listEnvironments(draft.name),
      studioClient.listDeployments(draft.name),
      studioClient.listDeploymentSnapshots(draft.name),
    ]).then(([nextEnvironments, nextDeployments, nextSnapshots]) => {
      if (!active) return;
      setEnvironments(nextEnvironments);
      setDeployments(nextDeployments);
      setDeploymentSnapshots(nextSnapshots);
    }).catch(() => {
      if (!active) return;
      setEnvironments([]);
      setDeployments([]);
      setDeploymentSnapshots([]);
    });
    return () => { active = false; };
  }, [draft.id, draft.name]);

  useEffect(() => {
    if (!activeDeployment) return;
    const timer = window.setTimeout(() => {
      void refreshDeployments().catch((error) => {
        setNotice(error instanceof Error ? error.message : "部署状态读取失败");
      });
    }, 1500);
    return () => window.clearTimeout(timer);
  }, [activeDeployment?.deployment.deploymentId, activeDeployment?.deployment.status]);

  useEffect(() => {
    if (!draft.id || !draft.name || !draft.publishedVersion) {
      setQualityGate(null);
      return;
    }
    let active = true;
    void studioClient.getQualityGate(draft.name, draft.publishedVersion).then((gate) => {
      if (active) setQualityGate(gate);
    }).catch(() => {
      if (active) setQualityGate(null);
    });
    return () => { active = false; };
  }, [draft.id, draft.name, draft.publishedVersion]);

  if (loading) {
    return <main className={styles.studioStateShell} id="main-content" aria-busy="true"><section className={styles.studioStateCard}><span className={styles.studioStateMark}>AS</span><h1>正在读取 Agent Studio</h1><p>正在恢复你的智能体草稿与能力目录。</p></section></main>;
  }
  if (loadError) {
    return <main className={styles.studioStateShell} id="main-content"><section className={styles.studioStateCard} role="alert"><span className={styles.studioStateMark}>!</span><h1>Agent Studio 数据暂不可用</h1><p>{loadError}</p><button type="button" onClick={() => window.location.reload()}>重新加载</button></section></main>;
  }

  return (
    <main className={styles.studioShell} id="main-content" data-studio-integration="api">
      <StudioSidebar active="agents">
        <div className={styles.railHeading}>
          <span>智能体</span>
          <button
            type="button"
            aria-label="新建智能体"
            disabled={!canEdit || saving}
            onClick={() => void startNewDraft()}
          >
            +
          </button>
        </div>

        <label className={styles.agentSearch}>
          <span className={styles.visuallyHidden}>搜索智能体</span>
          <input
            type="search"
            value={agentQuery}
            onChange={(event) => setAgentQuery(event.target.value)}
            placeholder="搜索名称、版本或状态"
          />
          <kbd>{filteredAgentRows.length}</kbd>
        </label>

        <nav className={styles.agentList} aria-label="智能体草稿和版本">
          {filteredAgentRows.map((agent) => (
            <button
              type="button"
              key={agent.draftId}
              className={agent.draftId === draft.id ? styles.agentRowActive : styles.agentRow}
              aria-current={agent.draftId === draft.id ? "page" : undefined}
              disabled={saving || Boolean(switchingDraftId) || agent.draftId === draft.id}
              onPointerEnter={() => {
                void studioClient.prefetchDraft(agent.draftId, agent.revision).catch(() => {});
              }}
              onFocus={() => {
                void studioClient.prefetchDraft(agent.draftId, agent.revision).catch(() => {});
              }}
              onClick={() => void selectDraft(agent.draftId)}
            >
              <span className={styles.agentMonogram} aria-hidden="true">
                {agent.displayName.slice(0, 1)}
              </span>
              <span className={styles.agentRowCopy}>
                <strong>{agent.displayName}</strong>
                <small>
                  {switchingDraftId === agent.draftId
                    ? "正在切换…"
                    : `${agent.spaceId ? "协作" : "个人"} · ${agent.version} · ${agent.publishedVersion ? `已发布 ${agent.publishedVersion}` : "草稿"} · r${agent.revision}`}
                </small>
              </span>
            </button>
          ))}
          {filteredAgentRows.length === 0 && (
            <div className={styles.agentListEmpty}>没有匹配的智能体</div>
          )}
        </nav>
      </StudioSidebar>

      <section className={styles.editorShell} data-readonly={!canEdit}>
        <header className={styles.editorHeader}>
          <div className={styles.titleBlock}>
            <div className={styles.eyebrow}>
              <span className={styles.draftDot} />
              {publishedCurrent ? "已发布" : "草稿"} · {draft.domain}
            </div>
            <div className={styles.titleLine}>
              <h1>{draft.displayName}</h1>
              <code>{draft.name}@{draft.version}</code>
            </div>
            <p>{draft.description}</p>
            <span className={styles.syncState} data-dirty={dirty} role="status">
              <i aria-hidden="true" />
              {saving
                ? "正在保存"
                : inspecting
                  ? "正在检查"
                  : dirty
                    ? "有未保存更改"
                    : draft.id
                      ? `已同步 r${draft.revision}`
                      : "尚未保存"}
            </span>
            {draft.publishedVersion && (
              <div className={styles.publicationBadge} data-current={publishedCurrent}>
                <span>{publishedCurrent ? "不可变版本已发布" : "存在历史发布版本"}</span>
                <code>{draft.name}@{draft.publishedVersion}</code>
                {draft.publishedHash && <code>{draft.publishedHash.slice(0, 12)}</code>}
                {draft.agentId && !draft.spaceId && (
                  <button
                    type="button"
                    ref={versionHistoryTriggerRef}
                    className={styles.versionHistoryButton}
                    aria-expanded={versionHistoryOpen}
                    aria-controls="personal-version-history"
                    onClick={() => {
                      setContractOpen(false);
                      setVersionHistoryOpen(true);
                    }}
                  >
                    版本历史
                    <small>{versionHistoryLoading ? "…" : personalVersions.length}</small>
                  </button>
                )}
              </div>
            )}
          </div>
          <div className={styles.headerActions}>
            {taskHref && (
              <Link
                className={`${styles.headerActionButton} ${styles.startTaskButton}`}
                href={taskHref}
                title={`使用当前版本 ${draft.name}@${taskVersion} 开始新任务`}
              >
                <HeaderActionIcon name="task" />
                <span>开始任务</span>
              </Link>
            )}
            <button
              type="button"
              className={`${styles.headerActionButton} ${styles.secondaryButton}`}
              disabled={!canEdit || saving || inspecting || !dirty}
              onClick={() => void saveDraft()}
            >
              <HeaderActionIcon name="save" />
              <span>{saving ? "保存中…" : "仅保存"}</span>
            </button>
            <button
              type="button"
              className={`${styles.headerActionButton} ${styles.publishButton}`}
              data-state={releaseTone}
              disabled={!canEdit || saving || inspecting || publishing}
              title="保存与检查会自动衔接；发布不可变版本前仍需一次明确点击"
              onClick={() => void handleReleaseAction()}
            >
              <HeaderActionIcon name="release" />
              <span>{releaseActionLabel}</span>
            </button>
            <button
              type="button"
              ref={contractTriggerRef}
              className={`${styles.headerActionButton} ${styles.contractToggleButton}`}
              data-ready={contract.ready}
              aria-expanded={contractOpen}
              aria-controls="effective-contract-drawer"
              onClick={() => setContractOpen(true)}
            >
              <i aria-hidden="true" />
              <HeaderActionIcon name="contract" />
              <span>运行契约</span>
              <small>{contract.ready ? "就绪" : contract.issues.length}</small>
            </button>
            <details className={styles.actionMenu} data-dismiss-on-outside>
              <summary
                className={`${styles.headerActionButton} ${styles.iconActionButton}`}
                aria-label="更多智能体操作"
                title="更多操作"
              >
                <span aria-hidden="true">•••</span>
              </summary>
              <div className={styles.actionMenuPopover}>
                <header className={styles.actionMenuHeader}>
                  <strong>更多操作</strong>
                  <small>导入、预览与导出</small>
                </header>
                <input
                  ref={bundleInputRef}
                  hidden
                  type="file"
                  accept=".zip,application/zip"
                  onChange={(event) => {
                    const file = event.currentTarget.files?.[0];
                    if (file) void importBundle(file);
                  }}
                />
                <button
                  type="button"
                  className={styles.actionMenuItem}
                  data-icon="↙"
                  disabled={!canEdit || importingBundle}
                  onClick={(event) => {
                    event.currentTarget.closest("details")?.removeAttribute("open");
                    bundleInputRef.current?.click();
                  }}
                >
                  <span><strong>{importingBundle ? "正在导入 Agent" : "导入 Agent / NexAU"}</strong><small>支持 Harness Bundle 与 NexAU ZIP，导入后可继续编辑</small></span>
                </button>
                <button
                  type="button"
                  className={styles.actionMenuItem}
                  data-icon="◇"
                  disabled={!canEdit || !draft.id || dirty || !serverValidation?.ready || creatingPreview}
                  title="创建绑定当前 Draft 双 Hash 的短时测试环境，并执行真实 Model、Sandbox 与 MCP Preflight"
                  onClick={(event) => {
                    event.currentTarget.closest("details")?.removeAttribute("open");
                    void createPreview();
                  }}
                >
                  <span><strong>{creatingPreview ? "正在创建 Preview" : "创建 Preview"}</strong><small>在隔离环境中完成真实预检</small></span>
                </button>
                <button
                  type="button"
                  className={styles.actionMenuItem}
                  data-icon="↓"
                  disabled={!draft.id || saving}
                  onClick={(event) => {
                    event.currentTarget.closest("details")?.removeAttribute("open");
                    void downloadBundle();
                  }}
                >
                  <span><strong>下载 Bundle</strong><small>获取当前不可变配置包</small></span>
                </button>
                <button
                  type="button"
                  className={styles.actionMenuItem}
                  data-icon="↗"
                  disabled={!draft.id || saving}
                  onClick={(event) => {
                    event.currentTarget.closest("details")?.removeAttribute("open");
                    void downloadNexauBundle();
                  }}
                >
                  <span><strong>导出 NexAU ZIP</strong><small>生成可导入 NexAU 的 Agent 包</small></span>
                </button>
              </div>
            </details>
          </div>
        </header>

        {conflict && (
          <div className={styles.conflictBanner} role="alert">
            <div><strong>控制面已有更新</strong><span>本地修改仍保留；加载控制面版本会放弃这些未保存内容。</span></div>
            <button
              type="button"
              disabled={saving || reloadingConflict}
              onClick={() => void reloadAfterConflict()}
            >
              {reloadingConflict ? "正在加载…" : "加载控制面版本"}
            </button>
          </div>
        )}
        {versionConflict && (
          <div className={styles.conflictBanner} role="alert">
            <div>
              <strong>该版本号已存在其他不可变内容</strong>
              <span>已发布版本不能覆盖。请修改版本号、保存并重新检查后再发布。</span>
            </div>
            <button type="button" onClick={() => setActiveSection("identity")}>修改版本号</button>
          </div>
        )}
        {releaseFeedbackOpen && serverValidation && (
          validationErrors.length
          + productionValidationErrors.length
          + validationWarnings.length
          + incompatibleMcpReferences.length > 0
        ) && (
          <aside
            className={styles.releaseFeedbackPopover}
            data-tone={validationErrors.length ? "blocked" : "warning"}
            aria-live="polite"
            aria-label="发布检查结果"
          >
            <header className={styles.releaseFeedbackSummary}>
              <span aria-hidden="true">!</span>
              <div>
                <strong>
                  {validationErrors.length
                    ? `${validationErrors.length} 项配置阻止发布`
                    : productionValidationErrors.length
                      ? `${productionValidationErrors.length} 项生产部署限制`
                      : `${validationWarnings.length} 项上线前提醒`}
                </strong>
                <small>检查结果不会占用编辑区；关闭后可从发布按钮再次打开。</small>
              </div>
              <button
                type="button"
                aria-label="关闭发布检查结果"
                onClick={() => setReleaseFeedbackOpen(false)}
              >
                ×
              </button>
            </header>
            <div className={styles.releaseFeedbackBody}>
              {validationErrors.length + productionValidationErrors.length > 0 && (
                <ul className={styles.releaseIssues}>
                  {[...validationErrors, ...productionValidationErrors].map((issue) => {
                    const section = validationIssueSection(issue);
                    const missingCoverage = missingEvaluationCoverage(issue);
                    const suggestedProfile = options.profiles.find(
                      (profile) => profile.profileId === issue.suggestedProfileIds[0],
                    );
                    return (
                      <li
                        key={`${issue.stage}:${issue.code}:${issue.path ?? ""}`}
                        data-stage={issue.stage}
                      >
                        <span aria-hidden="true">{issue.stage === "production" ? "P" : "!"}</span>
                        <div>
                          <strong>{validationIssueMessage(issue)}</strong>
                          <small>
                            {issue.stage === "production" ? "生产部署" : "发布"}
                            {" · "}{validationSectionLabels[section]}
                          </small>
                        </div>
                        <button
                          type="button"
                          onClick={() => {
                            setReleaseFeedbackOpen(false);
                            if (suggestedProfile) {
                              updateDraft({ executionProfile: suggestedProfile.profileId });
                            } else if (missingCoverage) {
                              updateDraft({
                                evalCases: [
                                  ...draft.evalCases,
                                  evaluationCoverageCase(missingCoverage, draft),
                                ],
                              });
                            }
                            setActiveSection(section);
                          }}
                        >
                          {suggestedProfile
                            ? `切换至 ${suggestedProfile.label}`
                            : missingCoverage
                              ? "一键补齐"
                              : "去处理"}
                        </button>
                      </li>
                    );
                  })}
                </ul>
              )}

              {validationWarnings.length > 0 && (
                <details className={styles.releaseWarnings}>
                  <summary>{validationWarnings.length} 项上线前提醒</summary>
                  <ul>
                    {validationWarnings.map((issue) => (
                      <li key={`${issue.code}:${issue.message}`}>{issue.message}</li>
                    ))}
                  </ul>
                </details>
              )}

              {incompatibleMcpReferences.length > 0 && (
                <div className={styles.releaseQuickFix}>
                  <span>
                    当前执行档位未允许：
                    <code>{incompatibleMcpReferences.join(", ")}</code>
                  </span>
                  <button
                    type="button"
                    onClick={() => {
                      updateDraft({
                        mcpServers: draft.mcpServers.filter(
                          (reference) => !incompatibleMcpReferences.includes(reference),
                        ),
                      });
                      setActiveSection("capabilities");
                    }}
                  >
                    移除不兼容 MCP
                  </button>
                </div>
              )}
            </div>
          </aside>
        )}
        {activePreview && (
          <div className={styles.previewBanner} data-status={activePreview.status} data-stale={activePreview.stale}>
            <div className={styles.previewIdentity}>
              <strong>
                {activePreview.stale ? "历史 Preview" : "Preview"} ·{" "}
                {previewStatusLabels[activePreview.status] ?? activePreview.status}
                {activePreview.stale ? "（不影响当前 Draft）" : ""}
              </strong>
              <span>
                测试身份 · Draft r{activePreview.draftRevision} · 到期 {new Date(activePreview.expiresAt).toLocaleString("zh-CN")}
                {activePreview.stale ? ` · 当前 Draft r${draft.revision}` : ""}
              </span>
            </div>
            <div className={styles.previewActions}>
              <button
                type="button"
                disabled={creatingPreview}
                onClick={() => {
                  if (
                    activePreview.stale
                    || ["cancelled", "failed", "expired"].includes(activePreview.status)
                  ) {
                    void createPreview();
                  } else {
                    void refreshPreview(activePreview.previewId);
                  }
                }}
              >
                {creatingPreview
                  ? "正在重新测试…"
                  : activePreview.stale
                    ? `重新测试 Draft r${draft.revision}`
                    : ["cancelled", "failed", "expired"].includes(activePreview.status)
                      ? "重新测试"
                      : "刷新状态"}
              </button>
              {!(["cancelled", "failed", "expired"] as string[]).includes(activePreview.status) && (
                <button type="button" onClick={() => void cancelPreview(activePreview.previewId)}>取消</button>
              )}
            </div>
            {activePreview.stale && (
              <p role="status">
                这是 Draft r{activePreview.draftRevision} 的不可变历史结果；读取刷新不会按当前 Draft 重跑。
              </p>
            )}
            {activePreview.preflightResult && (
              <details className={styles.preflightDisclosure}>
                <summary>
                  <span>
                    真实 Preflight · {activePreview.preflightResult.status}
                    {activePreview.preflightResult.errorCode ? ` · ${activePreview.preflightResult.errorCode}` : ""}
                  </span>
                  <small>
                    {preflightProgress(activePreview.preflightResult.checks)}
                  </small>
                </summary>
                <ol>
                  {activePreview.preflightResult.checks.map((check) => (
                    <li key={check.stage} data-status={check.status}>
                      <span aria-hidden="true">{check.status === "passed" ? "✓" : check.status === "skipped" ? "–" : "!"}</span>
                      <div>
                        <strong>{preflightStageLabels[check.stage]}</strong>
                        <small>{check.summary}{check.errorCode ? ` · ${check.errorCode}` : ""}</small>
                      </div>
                      <code>{check.durationMs}ms</code>
                    </li>
                  ))}
                </ol>
                {activePreview.preflightResult.errorCode && (
                  <p role="alert">
                    {activePreview.stale
                      ? `以下失败属于历史 Draft r${activePreview.draftRevision}，不能代表当前 Draft r${draft.revision}。`
                      : preflightErrorLabels[activePreview.preflightResult.errorCode]
                      ?? "Preflight 未通过。请根据失败阶段检查执行档位、凭据与目标环境。"}
                  </p>
                )}
                {activePreview.preflightResult.artifact && (
                  <p>
                    Artifact · {activePreview.preflightResult.artifact.name} · {activePreview.preflightResult.artifact.sizeBytes} B · {activePreview.preflightResult.artifact.sha256.slice(0, 12)}
                  </p>
                )}
              </details>
            )}
          </div>
        )}
        {!canEdit && (
          <div className={styles.readonlyBanner} role="status">
            当前为只读角色。可以查看配置和下载已通过校验的 Bundle，不能修改或保存草稿。
          </div>
        )}

        <section className={styles.lifecycleBar} aria-label="从草稿到部署的生命周期">
          <div className={styles.lifecycleSummary}>
            <span>发布状态</span>
            <strong>{lifecycleLabel}</strong>
            <small>{lifecycleDetail}</small>
          </div>
          <details className={styles.lifecycleDetails}>
            <summary>
              <span>查看完整发布链</span>
              <small>{activeLifecycleIndex + 1}/{lifecycleStages.length}</small>
            </summary>
            <ol>
              {lifecycleStages.map((stage, index) => {
                const state = index < activeLifecycleIndex
                  ? "complete"
                  : index === activeLifecycleIndex
                    ? "active"
                    : "pending";
                return (
                  <li key={stage.id} data-state={state}>
                    <i aria-hidden="true" />
                    <span>{stage.label}</span>
                  </li>
                );
              })}
            </ol>
          </details>
        </section>

        <div className={styles.editorBody}>
          <nav className={styles.sectionNav} aria-label="Agent 配置章节">
            {sections.map((section) => (
              <button
                type="button"
                key={section.id}
                className={activeSection === section.id ? styles.sectionActive : styles.sectionButton}
                onClick={() => setActiveSection(section.id)}
                aria-current={activeSection === section.id ? "step" : undefined}
              >
                <span>{section.label}</span>
                <span className={styles.sectionMeta}>
                  <small>{section.hint}</small>
                  <em>{sectionSummary(section.id)}</em>
                </span>
              </button>
            ))}
          </nav>

          <fieldset className={styles.panelViewport} disabled={!canEdit}>
            {activeSection === "identity" && (
              <section className={styles.configPanel} aria-labelledby="identity-title">
                <PanelHeading
                  id="identity-title"
                  kicker="01 / Identity"
                  title="定义清楚它负责什么"
                  description="名称和边界会进入不可变 Agent 版本；不要把实现细节写进业务说明。"
                />
                <div className={styles.formGrid}>
                  <Field label="显示名称">
                    <input
                      value={draft.displayName}
                      onChange={(event) => updateDraft({ displayName: event.target.value })}
                    />
                  </Field>
                  <Field label="Agent ID" hint="发布后不可原地修改">
                    <input
                      className={styles.monoInput}
                      value={draft.name}
                      onChange={(event) => updateDraft({ name: event.target.value })}
                    />
                  </Field>
                  <Field label="业务领域">
                    <input
                      className={styles.monoInput}
                      value={draft.domain}
                      onChange={(event) => updateDraft({ domain: event.target.value })}
                    />
                  </Field>
                  <Field label="版本" hint="修改已发布配置时自动递增补丁号，也可手动填写">
                    <input
                      className={styles.monoInput}
                      value={draft.version}
                      onChange={(event) => updateDraft({ version: event.target.value })}
                    />
                  </Field>
                  <Field label="场景说明" wide>
                    <textarea
                      rows={3}
                      value={draft.description}
                      onChange={(event) => updateDraft({ description: event.target.value })}
                    />
                  </Field>
                </div>
              </section>
            )}

            {activeSection === "model" && (
              <section className={styles.configPanel} aria-labelledby="model-title">
                <PanelHeading
                  id="model-title"
                  kicker="02 / Model"
                  title="选择经过平台验证的模型路由"
                  description="Agent 只引用路由和模型；Endpoint 与凭据始终由平台托管。"
                />
                <div className={styles.routeCards}>
                  {options.routes.map((route) => (
                    <button
                      type="button"
                      key={route.id}
                      className={draft.modelRoute === route.id ? styles.routeCardActive : styles.routeCard}
                      onClick={() =>
                        updateDraft({ modelRoute: route.id, model: route.models[0] })
                      }
                    >
                      <span className={styles.routeProvider}>{route.provider}</span>
                      <strong>{route.label}</strong>
                      <small>{route.capabilities.join(" · ")}</small>
                    </button>
                  ))}
                </div>
                <div className={styles.formGridSingle}>
                  <Field label="执行模型">
                    <select
                      value={draft.model}
                      onChange={(event) => updateDraft({ model: event.target.value })}
                    >
                      {(selectedRoute?.models ?? [draft.model]).map((model) => (
                        <option key={model} value={model}>{model}</option>
                      ))}
                    </select>
                  </Field>
                </div>
                <InfoStrip tone="neutral">
                  模型目录只展示已完成 Anthropic-compatible、流式输出和工具调用验证的组合。
                </InfoStrip>
              </section>
            )}

            {activeSection === "prompt" && (
              <section className={styles.configPanel} aria-labelledby="prompt-title">
                <PanelHeading
                  id="prompt-title"
                  kicker="03 / System Prompt"
                  title="写稳定行为契约，不堆易变知识"
                  description="生产门禁要求五个章节。业务 SOP 放入 Skills，确定性约束留给 Tools 和 Policy。"
                />
                <div
                  className={styles.promptWorkspace}
                  data-focus={promptFocusMode ? "true" : "false"}
                >
                  <aside className={styles.promptOutline} aria-label="System Prompt 结构">
                    <div className={styles.promptOutlineHeading}>
                      <div>
                        <span>行为契约结构</span>
                        <strong>{contract.promptSections} / 5 完整</strong>
                      </div>
                      <small>选择章节可定位；缺失章节会自动补到文末。</small>
                    </div>
                    <div className={styles.promptChecklist}>
                      {REQUIRED_PROMPT_HEADINGS.map((heading, index) => {
                        const present = draft.systemPrompt.includes(heading);
                        return (
                          <button
                            type="button"
                            key={heading}
                            className={present ? styles.checkPresent : styles.checkMissing}
                            onClick={() => moveToPromptSection(heading)}
                          >
                            <span aria-hidden="true">{present ? "✓" : "+"}</span>
                            <span>
                              <strong>{heading.replace("## ", "")}</strong>
                              <small>{present ? `章节 ${index + 1} · 已包含` : "点击补充"}</small>
                            </span>
                          </button>
                        );
                      })}
                    </div>
                    <div className={styles.promptBoundaryNote}>
                      <strong>放什么在这里？</strong>
                      <p>角色、目标、证据要求、安全边界和输出格式。</p>
                      <span>易变业务知识和长 SOP 请放入 Skills。</span>
                    </div>
                  </aside>
                  <div className={styles.promptEditorShell}>
                    <div className={styles.promptEditorToolbar}>
                      <div>
                        <span className={styles.promptFileMark} aria-hidden="true">M↓</span>
                        <span>
                          <strong>system.md</strong>
                          <small>{dirty ? "本轮修改尚未保存" : `已保存 · revision ${draft.revision}`}</small>
                        </span>
                      </div>
                      <div className={styles.promptEditorActions}>
                        <button
                          type="button"
                          onClick={() => setPromptFocusMode((current) => !current)}
                          aria-pressed={promptFocusMode}
                        >
                          {promptFocusMode ? "退出专注" : "专注编辑"}
                        </button>
                        <button
                          type="button"
                          onClick={() => void saveDraft()}
                          disabled={!canEdit || saving || !dirty}
                        >
                          {saving ? "保存中…" : "保存"}
                        </button>
                      </div>
                    </div>
                    <label className={styles.promptEditorLabel} htmlFor="system-prompt-editor">
                      Markdown
                      <span>Tab 缩进 · Ctrl / ⌘ S 保存</span>
                    </label>
                    <textarea
                      ref={promptEditorRef}
                      id="system-prompt-editor"
                      className={styles.codeEditor}
                      aria-label="System Prompt"
                      aria-describedby="system-prompt-stats"
                      spellCheck={false}
                      readOnly={!canEdit}
                      value={draft.systemPrompt}
                      onKeyDown={handlePromptEditorKeyDown}
                      onChange={(event) => updateDraft({ systemPrompt: event.target.value })}
                    />
                    <div className={styles.promptEditorFooter} id="system-prompt-stats">
                      <span>{draft.systemPrompt.split("\n").length} 行</span>
                      <span>{draft.systemPrompt.length.toLocaleString("zh-CN")} 字符</span>
                      <span>{new Blob([draft.systemPrompt]).size.toLocaleString("zh-CN")} bytes</span>
                      <span data-state={contract.promptSections === 5 ? "ready" : "missing"}>
                        {contract.promptSections === 5 ? "结构门禁已满足" : `缺少 ${5 - contract.promptSections} 个章节`}
                      </span>
                    </div>
                  </div>
                </div>
              </section>
            )}

            {activeSection === "orchestration" && (
              <section className={styles.configPanel} aria-labelledby="orchestration-title">
                <PanelHeading
                  id="orchestration-title"
                  kicker="04 / Collaboration"
                  title="让 Lead 负责决策，让专家并行取证"
                  description="Lead 是唯一面向用户的主线；Sub Agent 可直接绑定并打开 Studio 草稿编辑，正式发布 Lead 时再固定依赖版本。"
                />

                <div className={styles.orchestrationSummary} aria-label="协同运行摘要">
                  <div><span>前台主线</span><strong>1 Lead</strong></div>
                  <div><span>后台并行</span><strong>{contract.backgroundSubagentCount} Sub</strong></div>
                  <div>
                    <span>串行等待</span>
                    <strong>{contract.subagentCount - contract.backgroundSubagentCount} Sub</strong>
                  </div>
                  <div><span>委派入口</span><strong>Task · 受策略约束</strong></div>
                </div>

                <div className={styles.orchestrationGraph} aria-label="多智能体协同拓扑">
                  <article className={styles.leadAgentCard}>
                    <span className={styles.agentRoleBadge}>LEAD</span>
                    <div className={styles.agentIdentityMark} aria-hidden="true">L</div>
                    <div>
                      <strong>{draft.displayName}</strong>
                      <code>{draft.name}@{draft.version}</code>
                      <p>拆解任务、选择专家、交叉验证并汇总最终回答。</p>
                    </div>
                    <span className={styles.agentModeBadge}>前台主线</span>
                  </article>

                  {draft.subagents.length > 0 ? (
                    <>
                      <div className={styles.orchestrationFanout} aria-hidden="true">
                        <i />
                      </div>
                      <div className={styles.subagentTopology}>
                        {draft.subagents.map((subagent, index) => (
                          <article className={styles.subagentNode} key={`${subagent.alias}-${index}`}>
                            <div className={styles.subagentNodeHeader}>
                              <span className={styles.agentIdentityMark} aria-hidden="true">
                                {index + 1}
                              </span>
                              <span data-background={subagent.background}>
                                {subagent.background ? "并行" : "等待"}
                              </span>
                            </div>
                            <strong className={styles.subagentNodeName}>
                              {subagent.alias || "未命名角色"}
                            </strong>
                            <code className={styles.subagentNodeRef}>
                              {subagent.ref || "未固定版本"}
                            </code>
                            <p>{subagent.responsibility || "尚未定义职责"}</p>
                          </article>
                        ))}
                      </div>
                    </>
                  ) : (
                    <div className={styles.orchestrationEmpty}>
                      <strong>当前为单 Agent</strong>
                      <span>先新建另一个 Agent 草稿，即可绑定、编辑并在发布前完成检查。</span>
                    </div>
                  )}
                </div>

                <div className={styles.groupHeading}>
                  <div>
                    <h3>角色绑定</h3>
                    <p>角色别名用于 Lead 选择专家；同一通用 Agent 版本可绑定多个职责。</p>
                  </div>
                  <button type="button" className={styles.addSubagentButton} onClick={addSubagent}>
                    + 添加 Sub Agent
                  </button>
                </div>

                <div className={styles.subagentEditors}>
                  {draft.subagents.map((subagent, index) => {
                    const catalogAgent = subagentCandidates.find(
                      (agent) => agent.ref === subagent.ref,
                    );
                    return (
                    <article className={styles.subagentEditor} key={`${subagent.alias}-editor-${index}`}>
                      <header>
                        <div>
                          <span>SUB {String(index + 1).padStart(2, "0")}</span>
                          <strong>{subagent.alias || "未命名角色"}</strong>
                        </div>
                        <button
                          type="button"
                          onClick={() => removeSubagent(index)}
                          aria-label={`移除 ${subagent.alias || `Sub Agent ${index + 1}`}`}
                        >
                          移除
                        </button>
                      </header>
                      <div className={styles.formGrid}>
                        <Field label="角色别名" hint="Lead 调用名称">
                          <input
                            className={styles.monoInput}
                            value={subagent.alias}
                            onChange={(event) => updateSubagent(index, { alias: event.target.value })}
                          />
                        </Field>
                        <Field label="Sub Agent 草稿" hint="草稿可编辑；发布时固定版本">
                          <select
                            className={styles.monoInput}
                            value={subagent.ref}
                            onChange={(event) => updateSubagent(index, { ref: event.target.value })}
                          >
                            {!subagentCandidates.some((agent) => agent.ref === subagent.ref) && (
                              <option value={subagent.ref}>{subagent.ref || "未识别版本"}</option>
                            )}
                            {subagentCandidates.map((agent) => (
                              <option key={agent.ref} value={agent.ref}>
                                {agent.label} · {agent.ref}
                              </option>
                            ))}
                          </select>
                        </Field>
                        <Field label="职责与返回契约" wide>
                          <textarea
                            rows={3}
                            value={subagent.responsibility}
                            onChange={(event) =>
                              updateSubagent(index, { responsibility: event.target.value })
                            }
                          />
                        </Field>
                      </div>
                      {catalogAgent && (
                        <div className={styles.catalogBinding}>
                          <span data-status={catalogAgent.status}>
                            {catalogAgent.status === "approved" ? "已发布" : "草稿可编辑"}
                          </span>
                          <div>
                            <strong>{catalogAgent.label}</strong>
                            <small>{catalogAgent.description}</small>
                          </div>
                          <code>{catalogAgent.policy} · {catalogAgent.tools.join(" / ")}</code>
                          <button
                            type="button"
                            onClick={() => void editSubagentDraft(subagent.ref)}
                          >
                            打开并编辑
                          </button>
                        </div>
                      )}
                      <label className={styles.backgroundMode}>
                        <input
                          type="checkbox"
                          checked={subagent.background}
                          onChange={(event) =>
                            updateSubagent(index, { background: event.target.checked })
                          }
                        />
                        <span aria-hidden="true"><i /></span>
                        <div>
                          <strong>允许后台并行</strong>
                          <small>Lead 可同时派出多个独立任务；结果仍必须由 Lead 验收后汇总。</small>
                        </div>
                      </label>
                    </article>
                    );
                  })}
                </div>

                <InfoStrip tone="neutral">
                  每个 Sub Agent 继承自己的 Prompt、Skills、Builtin Tools、MCP、自定义算子、Policy 和轮次上限。草稿可以直接编辑；发布 Lead 时才要求依赖版本已发布且内容哈希固定。
                </InfoStrip>
              </section>
            )}

            {activeSection === "skills" && (
              <section className={styles.configPanel} aria-labelledby="skills-title">
                <PanelHeading
                  id="skills-title"
                  kicker="05 / Skills"
                  title="沉淀可复用的领域工作流"
                  description="发布时 Skill 及 references、scripts、assets 会一同进入不可变快照。"
                />
                <div className={styles.skillInstallBar}>
                  <div className={styles.skillTabs} role="tablist" aria-label="已安装 Skills">
                    {draft.skills.map((candidate) => (
                      <button
                        key={candidate.name}
                        type="button"
                        role="tab"
                        aria-selected={candidate.name === skill?.name}
                        onClick={() => {
                          setActiveSkillName(candidate.name);
                          setSkillConversationOpen(false);
                        }}
                      >
                        <span aria-hidden="true">S</span>
                        {candidate.name}
                      </button>
                    ))}
                  </div>
                  <input
                    ref={skillInputRef}
                    hidden
                    type="file"
                    accept=".zip,.md,application/zip,text/markdown"
                    onChange={(event) => {
                      const file = event.currentTarget.files?.[0];
                      if (file) void installSkill(file);
                    }}
                  />
                  <button
                    type="button"
                    className={styles.skillInstallButton}
                    disabled={!canEdit || importingSkill || saving}
                    onClick={() => skillInputRef.current?.click()}
                  >
                    {importingSkill ? "正在检查…" : "上传并安装 Skill"}
                  </button>
                  {skill && (
                    <button
                      type="button"
                      className={styles.skillUninstallButton}
                      disabled={!canEdit || importingSkill || saving}
                      onClick={() => void uninstallSkill(skill.name)}
                    >
                      卸载当前 Skill
                    </button>
                  )}
                </div>
                <InfoStrip tone="neutral">
                  支持单个 SKILL.md 或 ZIP。声明式内容直接安装到当前草稿；脚本和依赖只进入不可变快照，实际执行与安装仍走 Sandbox 权限门。
                </InfoStrip>
                {!skill && (
                  <div className={styles.skillEmpty}>
                    <strong>当前草稿尚未安装 Skill</strong>
                    <span>可上传 SKILL.md 或 ZIP；不安装 Skill 也可以继续配置和发布 Agent。</span>
                  </div>
                )}
                {skill && skillImportReport?.skillName === skill.name
                  && skillImportReport.findings.length > 0 && (
                    <details className={styles.skillImportFindings}>
                      <summary>
                        安装检查明细
                        <span>{skillImportReport.findings.length} 项 · 默认收起</span>
                      </summary>
                      {skillImportReport.warnings.length > 0 && (
                        <p>{skillImportReport.warnings.join("；")}</p>
                      )}
                      <ul>
                        {skillImportReport.findings.map((finding) => (
                          <li key={finding}>{finding}</li>
                        ))}
                      </ul>
                    </details>
                  )}
                {skill && (
                  <>
                <div className={styles.skillHeader}>
                  <span className={styles.skillGlyph} aria-hidden="true">S</span>
                  <div>
                    <strong>{skill.name}</strong>
                    <span>Agent 内置 Skill · 随版本发布</span>
                  </div>
                  <button
                    type="button"
                    aria-expanded={skillConversationOpen}
                    aria-controls="skill-conversation-builder"
                    disabled={!canEdit}
                    title={canEdit ? "通过多轮模型对话创建或改写 Skill" : "当前角色只有查看权限"}
                    onClick={() => setSkillConversationOpen((current) => !current)}
                  >
                    {skillConversationOpen ? "收起共创" : "对话创建"}
                  </button>
                </div>
                {skillConversationOpen && (
                  <SkillConversationBuilder
                    key={`${draft.id || "unsaved"}:${skill.name}`}
                    agent={{
                      name: draft.name,
                      displayName: draft.displayName,
                      domain: draft.domain,
                      description: draft.description,
                      modelRoute: draft.modelRoute,
                    }}
                    modelLabel={selectedRoute?.label ?? draft.model}
                    currentSkill={skill}
                    onClose={() => setSkillConversationOpen(false)}
                    onApply={(generatedSkill) => {
                      updateSkill(skill.name, generatedSkill);
                      setSkillConversationOpen(false);
                      setNotice(`已应用模型生成的 Skill：${generatedSkill.name} · 尚未保存`);
                    }}
                  />
                )}
                <div className={styles.formGridSingle}>
                  <Field label="Skill 描述">
                    <input
                      value={skill.description}
                      onChange={(event) =>
                        updateSkill(skill.name, {
                          ...skill,
                          description: event.target.value,
                        })
                      }
                    />
                  </Field>
                  <Field label="工作流说明">
                    <textarea
                      rows={10}
                      value={skill.instructions}
                      onChange={(event) =>
                        updateSkill(skill.name, {
                          ...skill,
                          instructions: event.target.value,
                        })
                      }
                    />
                  </Field>
                </div>
                <div className={styles.skillFiles}>
                  <div className={styles.groupHeading}>
                    <div>
                      <h3>Skill 附加文件</h3>
                      <p>风险规则、报告契约等内容会随 Skill 一起进入不可变 Bundle。</p>
                    </div>
                    <span>{skill.fileCount ?? skill.files?.length ?? 0} 个文件</span>
                  </div>
                  {(skill.files ?? []).slice(0, 200).map((file, index) => (
                    <article className={styles.skillFileCard} key={file.path}>
                      <code>{file.path}</code>
                      {file.content !== null && file.content !== undefined ? (
                        <textarea
                          aria-label={`编辑 ${file.path}`}
                          rows={8}
                          value={file.content}
                          onChange={(event) =>
                            updateSkill(skill.name, {
                              ...skill,
                              files: (skill.files ?? []).map((candidate, fileIndex) =>
                                fileIndex === index
                                  ? {
                                      path: candidate.path,
                                      content: event.target.value,
                                    }
                                  : candidate,
                              ),
                            })
                          }
                        />
                      ) : (
                        <div className={styles.skillBinaryFile}>
                          <span>{(file.binary ?? Boolean(file.contentBase64)) ? "BIN" : "REF"}</span>
                          <div>
                            <strong>
                              {(file.binary ?? Boolean(file.contentBase64))
                                ? "二进制 asset"
                                : "服务端保留文件"}
                            </strong>
                            <small>
                              约 {Math.ceil((file.sizeBytes ?? (file.contentBase64?.length ?? 0) * 0.75) / 1024).toLocaleString("zh-CN")} KiB
                              · 随 Skill 完整保存，不在编辑器中加载内容
                            </small>
                          </div>
                        </div>
                      )}
                    </article>
                  ))}
                  {skill.filesTruncated && (
                    <div className={styles.skillFilesEmpty}>
                      当前 Skill 共 {(skill.fileCount ?? 0).toLocaleString("zh-CN")} 个附加文件；
                      为保证编辑器流畅，仅加载前 200 个文件的元数据，其余文件仍完整保存在服务端并随版本发布。
                    </div>
                  )}
                  {(skill.fileCount ?? skill.files?.length ?? 0) === 0 && (
                    <div className={styles.skillFilesEmpty}>
                      当前 Skill 没有 references、scripts 或 assets。
                    </div>
                  )}
                </div>
                  </>
                )}
              </section>
            )}

            {activeSection === "capabilities" && (
              <section className={styles.configPanel} aria-labelledby="capabilities-title">
                <PanelHeading
                  id="capabilities-title"
                  kicker="06 / Capabilities"
                  title="只授予完成场景所需的能力"
                  description="能力是显式上限。没有选择的工具不会在运行时注入。"
                />

                <div className={styles.toolExposureControl}>
                  <div className={styles.toolExposureSummary}>
                    <span>工具加载</span>
                    <strong>
                      {draft.toolExposureMode === "on_demand"
                        ? "按需发现"
                        : "启动时加载"}
                    </strong>
                    <small>
                      目录 {toolDirectoryEntries} 项 · {
                        draft.toolExposureMode === "on_demand"
                          ? `${selectedMcpTools.length} 个 MCP Schema 命中后才进入上下文`
                          : "适合当前小型工具集"
                      }
                    </small>
                  </div>
                  <div
                    className={styles.toolExposureChoices}
                    role="group"
                    aria-label="工具加载方式"
                  >
                    <button
                      type="button"
                      data-active={draft.toolExposureMode === "eager"}
                      aria-pressed={draft.toolExposureMode === "eager"}
                      onClick={() => updateDraft({
                        toolExposureMode: "eager",
                        requiredCapabilities: draft.requiredCapabilities.filter(
                          (item) => item !== "tool_search",
                        ),
                      })}
                    >
                      <strong>启动时</strong>
                      <small>直接可用</small>
                    </button>
                    <button
                      type="button"
                      data-active={draft.toolExposureMode === "on_demand"}
                      aria-pressed={draft.toolExposureMode === "on_demand"}
                      disabled={!toolSearchEligible}
                      onClick={() => updateDraft({
                        toolExposureMode: "on_demand",
                        requiredCapabilities: Array.from(new Set([
                          ...draft.requiredCapabilities,
                          "tool_search",
                        ])),
                      })}
                    >
                      <strong>按需</strong>
                      <small>目录搜索</small>
                    </button>
                  </div>
                  <div
                    className={styles.toolExposureCompatibility}
                    data-ready={toolSearchEligible}
                  >
                    <i aria-hidden="true" />
                    <span>
                      {!toolSearchCompatible
                        ? "当前路由未审核 Tool Search，按需模式已锁定"
                        : draft.pythonTools.length > 0
                          ? "自定义算子必须启动时加载，移除后才可切换"
                          : selectedMcpTools.length === 0
                            ? "先选择至少一个 MCP 工具源"
                            : toolSearchRecommended
                              ? `${selectedMcpTools.length} 个 MCP 工具，建议按需加载`
                              : `${selectedMcpTools.length} 个 MCP 工具；可按需加载，达到 10 个时收益更明显`}
                    </span>
                  </div>
                </div>

                <div className={styles.groupHeading}>
                  <div>
                    <h3>工作区工具</h3>
                    <p>实际在强制隔离的 Sandbox 中执行。</p>
                  </div>
                  <span>{draft.builtinTools.length} 项已启用</span>
                </div>
                <div className={styles.toolGrid}>
                  {options.tools.map((tool) => {
                    const enabled = draft.builtinTools.includes(tool.id);
                    return (
                      <label key={tool.id} className={enabled ? styles.toolCardEnabled : styles.toolCard}>
                        <input
                          type="checkbox"
                          checked={enabled}
                          onChange={() => toggleBuiltin(tool.id)}
                        />
                        <span className={styles.toolCheck} aria-hidden="true">{enabled ? "✓" : ""}</span>
                        <span className={styles.toolCopy}>
                          <strong>{tool.label}</strong>
                          <small>{tool.description}</small>
                          <em data-risk={tool.risk}>{tool.approval}</em>
                        </span>
                        <code>{tool.id}</code>
                      </label>
                    );
                  })}
                </div>

                <div className={styles.groupHeading}>
                  <div>
                    <h3>自定义算子</h3>
                    <p>源码随 Bundle 导入导出，调用时只在隔离 Sandbox 内执行。</p>
                  </div>
                  <button
                    type="button"
                    className={styles.addSubagentButton}
                    onClick={addPythonTool}
                  >
                    + 新建自定义算子
                  </button>
                </div>
                <div className={styles.subagentEditors}>
                  {draft.pythonTools.map((tool, index) => (
                    <article className={styles.subagentEditor} key={`${tool.name}-${index}`}>
                      <header>
                        <div>
                          <span>PY {String(index + 1).padStart(2, "0")}</span>
                          <strong>{tool.name || "未命名算子"}</strong>
                        </div>
                        <button
                          type="button"
                          onClick={() => removePythonTool(index)}
                          aria-label={`移除 ${tool.name || `自定义算子 ${index + 1}`}`}
                        >
                          移除
                        </button>
                      </header>
                      <div className={styles.formGrid}>
                        <Field label="工具名称" hint="小写字母、数字和下划线">
                          <input
                            className={styles.monoInput}
                            value={tool.name}
                            onChange={(event) =>
                              updatePythonTool(index, { name: event.target.value })
                            }
                          />
                        </Field>
                        <Field label="工具说明">
                          <input
                            value={tool.description}
                            onChange={(event) =>
                              updatePythonTool(index, { description: event.target.value })
                            }
                          />
                        </Field>
                        <div className={styles.pythonToolWorkspace}>
                          <JsonSchemaCodeEditor
                            key={`${tool.name}-schema-${JSON.stringify(tool.inputSchema)}`}
                            value={tool.inputSchema}
                            onCommit={(inputSchema) =>
                              updatePythonTool(index, { inputSchema })
                            }
                            onInvalid={(message) =>
                              setNotice(
                                `Input Schema 不是有效 JSON：${tool.name} · ${message}`,
                              )
                            }
                          />
                          <PythonCodeEditor
                            value={tool.code}
                            onChange={(code) => updatePythonTool(index, { code })}
                          />
                        </div>
                      </div>
                    </article>
                  ))}
                  {draft.pythonTools.length === 0 && (
                    <div className={styles.skillFilesEmpty}>
                      暂无自定义算子。新建后会自动切换为启动时加载，并随 Bundle 保存源码。
                    </div>
                  )}
                </div>

                <div className={styles.groupHeading}>
                  <div>
                    <h3>数据与联网能力</h3>
                    <p>通过平台注册的逻辑 MCP，不接受任意 URL 或内联密钥。</p>
                  </div>
                  <span>
                    {visibleMcpOptions.filter((item) => draft.mcpServers.includes(item.id)).length} 项已启用
                  </span>
                </div>
                {visibleMcpOptions.filter((mcp) => mcp.category !== "knowledge").map((mcp) => {
                  const enabled = draft.mcpServers.includes(mcp.id);
                  return (
                    <label key={mcp.id} className={enabled ? styles.mcpCardEnabled : styles.mcpCard}>
                      <input
                        type="checkbox"
                        checked={enabled}
                        onChange={() => toggleMcp(mcp.id)}
                      />
                      <span className={styles.mcpSignal} aria-hidden="true"><i /><i /><i /></span>
                      <span className={styles.mcpCopy}>
                        <span className={styles.mcpTitleLine}>
                          <strong>{mcp.label}</strong>
                          <span>只读</span>
                          <span>外部服务</span>
                        </span>
                        <small>{mcp.description}</small>
                        <code>{mcp.tools.join(" · ")}</code>
                      </span>
                      <span className={styles.switchVisual} aria-hidden="true"><i /></span>
                    </label>
                  );
                })}
                {draft.mcpServers.includes("tavily-readonly") && (
                  <InfoStrip tone="warning">
                    检索词和待抽取 URL 会发送给 Tavily。发布部署前必须从实际 Sandbox 检查凭据、MCP tools/list 与公网可达性；这不会开放任意 Bash 网络访问。
                  </InfoStrip>
                )}

                {visibleMcpOptions.some((item) => item.category === "knowledge") && (
                  <>
                    <div className={styles.groupHeading}>
                      <div>
                        <h3>外部知识库</h3>
                        <p>通过已审核的 MCP 检索工具访问；资料、切片与向量均保留在外部系统。</p>
                      </div>
                      <span>
                        {visibleMcpOptions.filter((item) => item.category === "knowledge" && draft.mcpServers.includes(item.id)).length} 个已绑定
                      </span>
                    </div>
                    {visibleMcpOptions.filter((item) => item.category === "knowledge").map((mcp) => {
                      const enabled = draft.mcpServers.includes(mcp.id);
                      return (
                        <label
                          key={mcp.id}
                          className={enabled ? styles.mcpCardEnabled : styles.mcpCard}
                        >
                          <input
                            type="checkbox"
                            checked={enabled}
                            onChange={() => toggleMcp(mcp.id)}
                          />
                          <span className={styles.mcpSignal} aria-hidden="true">
                            <i /><i /><i />
                          </span>
                          <span className={styles.mcpCopy}>
                            <span className={styles.mcpTitleLine}>
                              <strong>{mcp.label}</strong>
                              <span>外部检索</span>
                              <span>{mcp.tools.length} 个工具</span>
                            </span>
                            <small>{mcp.description}</small>
                            <code>{mcp.tools.join(" · ")}</code>
                          </span>
                          <span className={styles.switchVisual} aria-hidden="true"><i /></span>
                        </label>
                      );
                    })}
                  </>
                )}
              </section>
            )}

            {activeSection === "runtime" && (
              <section className={styles.configPanel} aria-labelledby="runtime-title">
                <PanelHeading
                  id="runtime-title"
                  kicker="07 / Runtime"
                  title="隔离是生产基线，不是 Agent 开关"
                  description="构建者声明能力，平台把执行档位绑定到 Daytona、gVisor 或其他安全后端。"
                />
                <div className={styles.runtimeRecommendation}>
                  <span>当前场景推荐</span>
                  <div>
                    <strong>{recommendedRuntime.label}</strong>
                    <p>{recommendedRuntime.description}</p>
                    <small>
                      {recommendedRuntime.policy} · 最多 {recommendedRuntime.maxTurns} 轮 · 无硬超时、预算或 Token 中止
                    </small>
                  </div>
                  <button
                    type="button"
                    disabled={!canEdit || recommendationApplied}
                    onClick={() =>
                      updateDraft({
                        policy: recommendedRuntime.policy,
                        maxTurns: recommendedRuntime.maxTurns,
                        timeoutSeconds: null,
                        maxBudgetUsd: null,
                        maxModelTokens: null,
                        restoreSession: true,
                        archiveOnComplete: true,
                      })
                    }
                  >
                    {recommendationApplied ? "已采用" : "应用推荐配置"}
                  </button>
                </div>
                <div className={styles.isolationCard}>
                  <span className={styles.isolationGlyph} aria-hidden="true"><i /><i /></span>
                  <div>
                    <strong>隔离执行 · 平台托管</strong>
                    <p>工作区、进程、网络和生命周期由部署环境统一约束。</p>
                  </div>
                  <span className={styles.lockedBadge}>生产强制</span>
                </div>
                <div className={styles.runtimeAssurances}>
                  <article className={styles.identityBoundary}>
                    <header>
                      <div><span>IDENTITY</span><strong>独立工作负载身份</strong></div>
                      <em>发布时生成</em>
                    </header>
                    <dl>
                      <div><dt>主体</dt><dd>agent:{draft.name}@{draft.version}</dd></div>
                      <div><dt>入站</dt><dd>继承已认证用户与租户上下文</dd></div>
                      <div><dt>出站</dt><dd>按 Tool / MCP 单独注入运行时凭据</dd></div>
                    </dl>
                  </article>
                  <article className={styles.continuityBoundary}>
                    <header>
                      <div><span>CONTINUITY</span><strong>恢复与归档语义</strong></div>
                      <em>显式配置</em>
                    </header>
                    <label>
                      <input
                        type="checkbox"
                        checked={draft.restoreSession}
                        onChange={(event) => updateDraft({ restoreSession: event.target.checked })}
                      />
                      <span>恢复同一会话的 SDK 上下文</span>
                    </label>
                    <label>
                      <input
                        type="checkbox"
                        checked={draft.archiveOnComplete}
                        onChange={(event) => updateDraft({ archiveOnComplete: event.target.checked })}
                      />
                      <span>运行结束后归档沙箱工作区</span>
                    </label>
                    <p>当前保障会话与审批恢复；不宣称支持任意工具步骤的持久化 checkpoint。</p>
                  </article>
                </div>
                <div className={styles.formGrid}>
                  <Field label="Execution Profile" hint="平台托管 · 版本固定">
                    <select
                      value={draft.executionProfile}
                      onChange={(event) => updateDraft({ executionProfile: event.target.value })}
                    >
                      {options.profiles.map((profile) => (
                        <option key={`${profile.profileId}@${profile.version}`} value={profile.profileId}>
                          {profile.label} · v{profile.version} · {profile.sandboxProvider}
                          {profile.productionAllowed ? "" : " · 仅 Preview"}
                        </option>
                      ))}
                    </select>
                  </Field>
                  {options.profiles.find((profile) => profile.profileId === draft.executionProfile) && (
                    <div className={styles.profileFacts}>
                      {(() => {
                        const profile = options.profiles.find(
                          (item) => item.profileId === draft.executionProfile,
                        );
                        if (!profile) return null;
                        return <>
                          <span>{profile.cpuMillis}m CPU</span>
                          <span>{profile.memoryMiB} MiB 内存</span>
                          <span>{profile.diskMiB} MiB 磁盘</span>
                          <span>TTL {profile.ttlSeconds}s</span>
                          <span>{profile.networkPolicyId}</span>
                          {!profile.productionAllowed && <span>禁止生产发布</span>}
                        </>;
                      })()}
                    </div>
                  )}
                  <div
                    className={styles.executionProfileAdvisor}
                    data-state={
                      selectedProfileSupportsMcp && selectedExecutionProfile?.productionAllowed
                        ? "ready"
                        : recommendedExecutionProfile
                          ? "recommend"
                          : "blocked"
                    }
                  >
                    <i aria-hidden="true" />
                    <div>
                      <span>PROFILE COMPATIBILITY</span>
                      <strong>
                        {!selectedProfileSupportsMcp
                          ? `当前档位不兼容 ${incompatibleMcpReferences.join("、") || "已选能力"}`
                          : !selectedExecutionProfile?.productionAllowed
                            ? "当前档位仅限 Preview"
                            : "当前档位兼容，具备生产资格"}
                      </strong>
                      <small>
                        {productionExecutionProfiles.length
                          ? `兼容生产档位：${productionExecutionProfiles.map((profile) => profile.label).join("、")}`
                          : compatibleExecutionProfiles.length
                            ? `仅 Preview 可用：${compatibleExecutionProfiles.map((profile) => profile.label).join("、")}`
                            : "没有档位能同时满足当前 MCP；请移除不兼容能力或让管理员更新 Egress 授权。"}
                      </small>
                    </div>
                    {recommendedExecutionProfile
                      && recommendedExecutionProfile.profileId !== draft.executionProfile ? (
                        <button
                          type="button"
                          disabled={!canEdit || saving || inspecting}
                          onClick={() => void applyRecommendedExecutionProfile(
                            recommendedExecutionProfile.profileId,
                          )}
                        >
                          {saving || inspecting
                            ? "切换并检查中…"
                            : `切换、保存并检查 ${recommendedExecutionProfile.label}`}
                        </button>
                      ) : !recommendedExecutionProfile ? (
                        <button
                          type="button"
                          onClick={() => setActiveSection("capabilities")}
                        >
                          调整 MCP
                        </button>
                      ) : null}
                  </div>
                  <Field label="权限 Profile" wide>
                    <select
                      value={draft.policy}
                      onChange={(event) => updateDraft({ policy: event.target.value })}
                    >
                      {policyOptions.map((policy) => (
                        <option key={policy.id} value={policy.id}>
                          {policy.label} · {policy.description}
                        </option>
                      ))}
                    </select>
                  </Field>
                  <div className={styles.permissionCoverage}>
                    <i aria-hidden="true" />
                    <div>
                      <strong>
                        当前 Agent 声明 {draft.builtinTools.length + selectedMcpTools.length} 个工具
                      </strong>
                      <span>
                        {draft.policy === "production-read-only"
                          ? `只读 Profile 覆盖工作区读取和 ${selectedMcpTools.length} 个已审核 MCP 工具；其他调用默认拒绝。`
                          : `${draft.policy} 将按已发布规则逐项判定；未匹配规则默认拒绝。`}
                      </span>
                    </div>
                  </div>
                  <Field label="Agent 最大轮次" hint="建议 64；留空表示不限制">
                    <input
                      type="number"
                      min={1}
                      value={draft.maxTurns ?? ""}
                      placeholder="不限制"
                      onChange={(event) => updateDraft({
                        maxTurns: event.target.value ? Number(event.target.value) : null,
                      })}
                    />
                  </Field>
                  <Field label="硬超时（秒）" hint="留空表示不以时长中止">
                    <input
                      type="number"
                      min={1}
                      value={draft.timeoutSeconds ?? ""}
                      placeholder="不限制"
                      onChange={(event) => updateDraft({
                        timeoutSeconds: event.target.value ? Number(event.target.value) : null,
                      })}
                    />
                  </Field>
                  <Field label="可绑定 Sub 上限">
                    <input
                      type="number"
                      min={1}
                      max={32}
                      value={draft.maxSubagents}
                      onChange={(event) => updateDraft({ maxSubagents: Number(event.target.value) })}
                    />
                  </Field>
                  <Field label="单 Run 子任务上限">
                    <input
                      type="number"
                      min={1}
                      max={128}
                      value={draft.maxSubagentTasks}
                      onChange={(event) => updateDraft({ maxSubagentTasks: Number(event.target.value) })}
                    />
                  </Field>
                  <Field label="Sub 并发上限">
                    <input
                      type="number"
                      min={1}
                      max={16}
                      value={draft.maxConcurrentSubagents}
                      onChange={(event) => updateDraft({ maxConcurrentSubagents: Number(event.target.value) })}
                    />
                  </Field>
                  <p className={styles.fieldHint}>
                    每个 Sub 使用独立会话，只把结果返回 Lead。根 Agent 默认最多 64 轮，不设置时长、模型 Token 或费用硬中止；委派深度固定为 1，隔离与权限边界仍然生效。
                  </p>
                </div>
                <GovernanceControlPlane
                  agentName={draft.name}
                  policyId={draft.policy}
                  mcpReferences={draft.mcpServers}
                  mcpTools={selectedMcpTools}
                  canManage={canPublish}
                  policies={governedPolicies}
                  onPoliciesChanged={setGovernedPolicies}
                />
              </section>
            )}

            {activeSection === "evaluation" && (
              <section className={styles.configPanel} aria-labelledby="evaluation-title">
                <PanelHeading
                  id="evaluation-title"
                  kicker="08 / Quality gate"
                  title="用真实失败路径证明它可以发布"
                  description="结构检查只是第一层；上线前仍要在固定版本和真实 Sandbox 中跑 live eval。"
                />
                {taskHref && (
                  <div className={styles.releaseTaskShortcut}>
                    <div>
                      <strong>用已发布版本验证真实任务</strong>
                      <span>{draft.name}@{draft.publishedVersion}</span>
                    </div>
                    <Link href={taskHref}>开始任务</Link>
                  </div>
                )}
                <div className={styles.evalMode}>
                  <div>
                    <strong>Agent Eval</strong>
                    <span>
                      {draft.evaluationEnabled
                        ? "已启用：基础覆盖参与发布检查，可固化 Dataset 并运行版本评测。"
                        : "已关闭：此 Agent 不执行 Eval，也不会被 Eval 覆盖或 Dataset 门禁阻断。"}
                    </span>
                  </div>
                  <label>
                    <input
                      type="checkbox"
                      checked={draft.evaluationEnabled}
                      disabled={!canEdit}
                      onChange={(event) =>
                        updateDraft({ evaluationEnabled: event.target.checked })
                      }
                    />
                    <span aria-hidden="true"><i /></span>
                    <em>{draft.evaluationEnabled ? "开启" : "关闭"}</em>
                  </label>
                </div>
                {draft.evaluationEnabled ? (
                  <>
                    <div className={styles.evalToolbar}>
                      <div>
                        {(["happy", "ambiguous", "safety"] as const).map((tag) => (
                          <span
                            key={tag}
                            data-complete={draft.evalCases.some((testCase) => testCase.tag === tag)}
                          >
                            {evaluationCoverageLabels[tag]}
                          </span>
                        ))}
                      </div>
                      <button type="button" onClick={() => setEvalManagerOpen(true)}>
                        管理评测场景
                      </button>
                    </div>
                    <div className={styles.evalDatasetSummary}>
                      <div>
                        <strong>{draft.evalCases.length} 条评测场景</strong>
                        <span>场景编辑与文件导入已移至独立评测集管理器。</span>
                      </div>
                      {(["happy", "ambiguous", "safety"] as const).map((tag) => (
                        <span key={tag}>
                          {evaluationCoverageLabels[tag]} {draft.evalCases.filter((testCase) => testCase.tag === tag).length}
                        </span>
                      ))}
                      <button type="button" onClick={() => setEvalManagerOpen(true)}>
                        打开评测集管理器
                      </button>
                    </div>
                <section className={styles.evalControlPlane} aria-label="持久化评测控制面">
                  <header>
                    <div>
                      <span>耐久 Eval 控制面</span>
                      <strong>
                        {latestDataset
                          ? `${latestDataset.name} · v${latestDataset.version}`
                          : "尚未启用发布必测集"}
                      </strong>
                      <small>
                        {latestDataset
                          ? "最新 Dataset 会成为环境部署门禁；每个 Case 使用独立 Session。"
                          : "可直接发布 Agent 版本；固化后，这组用例会成为环境部署前的必测门禁。"}
                      </small>
                    </div>
                    <div className={styles.evalControlActions}>
                      <button
                        type="button"
                        disabled={!canEdit || !draft.id || dirty || Boolean(evalAction)}
                        onClick={() => void createEvalDataset()}
                      >
                        {evalAction === "dataset"
                          ? "固化中…"
                          : latestDataset
                            ? "创建新 Dataset 版本"
                            : "设为发布必测集"}
                      </button>
                      <button
                        type="button"
                        disabled={!canEdit || !latestDataset || !draft.publishedVersion || Boolean(evalAction) || Boolean(activeEvalRun && ["queued", "running", "cancelling"].includes(activeEvalRun.run.status))}
                        onClick={() => latestDataset && void startEvalRun(latestDataset)}
                      >
                        {evalAction === "run"
                          ? "排队中…"
                          : `运行 ${draft.publishedVersion ?? "已发布版本"} Eval`}
                      </button>
                    </div>
                  </header>

                  {activeEvalRun ? (
                    <article className={styles.evalRunCard} data-status={activeEvalRun.run.status}>
                      <div className={styles.evalRunSummary}>
                        <span className={styles.evalRunSignal} aria-hidden="true" />
                        <div>
                          <strong>
                            {activeEvalRun.run.status} · {activeEvalRun.passedCases}/{activeEvalRun.totalCases} 通过
                          </strong>
                          <small>
                            {activeEvalRun.run.agentName}@{activeEvalRun.run.agentVersion} · Dataset v{activeEvalRun.run.datasetVersion}
                            {activeEvalRun.run.activeCaseId ? ` · 正在处理 ${activeEvalRun.run.activeCaseId}` : ""}
                          </small>
                        </div>
                        {["queued", "running", "cancelling"].includes(activeEvalRun.run.status) && (
                          <button
                            type="button"
                            disabled={Boolean(evalAction)}
                            onClick={() => void cancelEvalRun(activeEvalRun.run.evalRunId)}
                          >
                            {evalAction === "cancel" ? "取消中…" : "取消"}
                          </button>
                        )}
                      </div>
                      <ol className={styles.evalCaseResults}>
                        {activeEvalRun.cases.map((result) => (
                          <li key={result.caseId} data-status={result.status}>
                            <span>{result.passed ? "✓" : "!"}</span>
                            <div>
                              <strong>{result.caseId}</strong>
                              <small>
                                {result.status} · {result.durationSeconds.toFixed(2)}s
                                {result.tools.length ? ` · ${result.tools.join(" / ")}` : ""}
                              </small>
                              {result.failures.length > 0 && <p>{result.failures.join("；")}</p>}
                            </div>
                            <code>{result.runId ? result.runId.slice(-10) : "no-run"}</code>
                          </li>
                        ))}
                      </ol>
                      {activeEvalRun.run.artifacts.length > 0 && (
                        <div className={styles.evalArtifacts}>
                          {activeEvalRun.run.artifacts.map((artifact) => (
                            <button
                              type="button"
                              key={artifact.artifactId}
                              onClick={() => void studioClient.downloadEvalArtifact(activeEvalRun.run.evalRunId, artifact.artifactId)}
                            >
                              下载 {artifact.name} · {artifact.sizeBytes} B
                            </button>
                          ))}
                        </div>
                      )}
                    </article>
                  ) : (
                    <div className={styles.evalRunEmpty}>
                      {!latestDataset
                        ? "当前没有发布门禁。需要更严格的上线保障时，再把上方用例设为必测集。"
                        : !draft.publishedVersion
                          ? "先发布不可变 Agent 版本，再运行这组必测用例。"
                          : "必测集已准备好，可以运行已发布版本 Eval。"}
                    </div>
                  )}

                  {agentEvalRuns.length > 1 && (
                    <details className={styles.evalHistory}>
                      <summary>版本对比 · 最近 {agentEvalRuns.length} 轮</summary>
                      <div>
                        {agentEvalRuns.slice(0, 6).map((item) => (
                          <span key={item.run.evalRunId} data-status={item.run.status}>
                            <code>{item.run.agentVersion}</code>
                            <strong>{item.passedCases}/{item.totalCases}</strong>
                            <small>{item.run.status} · Dataset v{item.run.datasetVersion}</small>
                          </span>
                        ))}
                      </div>
                    </details>
                  )}
                </section>
                  </>
                ) : (
                  <div className={styles.evalDisabled}>
                    <strong>Eval 已对当前 Agent 关闭</strong>
                    <span>现有用例配置会保留，重新开启后继续使用，不会删除历史 Dataset 或运行记录。</span>
                  </div>
                )}
                <div className={styles.releaseGate}>
                  <div>
                    <span>本地结构门禁</span>
                    <strong>{contract.ready ? "可生成发布包" : "存在阻塞问题"}</strong>
                  </div>
                  <div>
                    <span>真实环境预检</span>
                    <strong>{activePreview?.preflightResult?.status === "passed" ? "Model / MCP / Sandbox 已通过" : "尚未取得真实 Preflight 证明"}</strong>
                  </div>
                  <div>
                    <span>固定版本轨迹评测</span>
                    <strong>
                      {evalGate
                        ? `${evalGate.passedDatasets}/${evalGate.requiredDatasets} 必测 Dataset 通过`
                        : `${draft.evalCases.length} 用例待固化`}
                    </strong>
                  </div>
                  <div>
                    <span>运行质量门禁</span>
                    <strong>
                      {qualityGate
                        ? qualityGate.passed
                          ? "无阻断问题"
                          : `${qualityGate.blockingIncidentIds.length} 项质量问题阻断发布`
                        : draft.publishedVersion
                          ? "等待已发布版本样本"
                          : "发布版本后生效"}
                    </strong>
                  </div>
                </div>
                <div className={styles.releaseArchitecture} aria-label="发布架构">
                  <article>
                    <span>PREVIEW</span>
                    <strong>临时隔离环境</strong>
                    <p>结构检查通过后创建短时试跑环境；失败不污染任何正式版本。</p>
                    <code>TTL 60 min · 真实 Preflight</code>
                  </article>
                  <article>
                    <span>VERSION</span>
                    <strong>不可变 Bundle</strong>
                    <p>Prompt、Skills、Tools、Sub Agent 固定引用和策略一次性快照。</p>
                    <code>{draft.name}@{draft.version}</code>
                  </article>
                  <article>
                    <span>ENVIRONMENT</span>
                    <strong>按环境晋级</strong>
                    <p>测试、灰度、生产只切换版本指针；保留历史以支持快速回退。</p>
                    <code>test → canary → production</code>
                  </article>
                </div>
                <section className={styles.deploymentControlPlane} aria-label="环境部署控制面">
                  <header>
                    <div>
                      <span>DEPLOYMENT CONTROL PLANE</span>
                      <strong>环境指针、灰度与可验证回滚</strong>
                      <small>发布不修改 Agent Version；新 Session 解析当前路由，已存在 Session 始终固定原快照。</small>
                    </div>
                    {activeDeployment && (
                      <em>{activeDeployment.deployment.environment} · {activeDeployment.deployment.status}</em>
                    )}
                  </header>
                  <div className={styles.environmentGrid}>
                    {environments.map((environment) => {
                      const currentRoutes = environment.routes.map((route) => ({
                        ...route,
                        snapshot: snapshotById.get(route.snapshotId),
                      }));
                      const alreadyCurrent = currentRoutes.some(
                        (route) => route.snapshot?.agentVersion === draft.publishedVersion,
                      );
                      const profileCompatible =
                        environment.resourcePolicy.executionProfileId
                        === draft.executionProfile;
                      return (
                        <article key={environment.name} data-environment={environment.name}>
                          <div className={styles.environmentHeading}>
                            <span>{environment.name.toUpperCase()}</span>
                            <code>revision {environment.revision}</code>
                          </div>
                          <strong>
                            {currentRoutes.length
                              ? currentRoutes.map((route) => `${route.snapshot?.agentVersion ?? "未知版本"} · ${route.weight}%`).join(" / ")
                              : "尚未部署"}
                          </strong>
                          <small>
                            {environment.healthySnapshotId
                              ? `健康快照 ${environment.healthySnapshotId.slice(-10)}`
                              : "等待首次健康发布"}
                          </small>
                          <button
                            type="button"
                            disabled={
                              !canPublish
                              || !draft.publishedVersion
                              || !draft.publishedPackageHash
                              || !evalGate?.passed
                              || alreadyCurrent
                              || !profileCompatible
                              || Boolean(deploymentAction)
                            }
                            onClick={() => void promoteTo(environment)}
                          >
                            {deploymentAction === `promote:${environment.name}`
                              ? "提交中…"
                              : alreadyCurrent
                                ? "当前版本"
                                : !draft.publishedVersion
                                  ? "先发布 Agent 版本"
                                : !profileCompatible
                                  ? "执行 Profile 不匹配"
                                  : !evalGate
                                    ? "正在检查发布门禁"
                                    : !evalGate.passed
                                      ? "先通过发布必测集"
                                : environment.name === "canary" && environment.healthySnapshotId
                                  ? "灰度 10% 新会话"
                                  : `发布 ${draft.publishedVersion ?? "版本"}`}
                          </button>
                        </article>
                      );
                    })}
                  </div>
                  {capabilities && (
                    <EnvironmentPolicyControlPlane
                      agentName={draft.name}
                      environments={environments}
                      capabilities={capabilities}
                      canManage={canPublish}
                      onUpdated={(updated) => {
                        setEnvironments((current) => current.map((item) =>
                          item.name === updated.name ? updated : item
                        ));
                        setNotice(
                          `${updated.name} 环境策略已更新到 r${updated.policyRevision}`,
                        );
                      }}
                    />
                  )}
                  <details className={styles.deploymentHistory} open={deployments.some((item) => item.deployment.status === "failed")}>
                    <summary>部署记录与版本差异 · {deployments.length} 次</summary>
                    <div>
                      {deployments.slice(0, 8).map((item) => {
                        const previous = item.deployment.previousSnapshotId
                          ? snapshotById.get(item.deployment.previousSnapshotId)
                          : undefined;
                        const environment = environments.find(
                          (candidate) => candidate.name === item.deployment.environment,
                        );
                        const canRollback = Boolean(
                          environment
                          && item.deployment.status === "succeeded"
                          && environment.healthySnapshotId !== item.target.snapshotId,
                        );
                        return (
                          <article key={item.deployment.deploymentId} data-status={item.deployment.status}>
                            <span>{item.deployment.action === "rollback" ? "回滚" : "发布"}</span>
                            <div>
                              <strong>
                                {item.deployment.environment} · {previous?.agentVersion ?? "空环境"} → {item.target.agentVersion}
                              </strong>
                              <small>
                                {item.deployment.status}
                                {item.deployment.canaryPercent < 100 ? ` · 新会话 ${item.deployment.canaryPercent}%` : " · 全量"}
                                {item.deployment.errorCode ? ` · ${item.deployment.errorCode}` : ""}
                              </small>
                              <code>{previous?.packageHash.slice(0, 10) ?? "—"} → {item.target.packageHash.slice(0, 10)}</code>
                            </div>
                            {canRollback && environment && (
                              <button
                                type="button"
                                disabled={Boolean(deploymentAction)}
                                onClick={() => void rollbackTo(environment, item.target)}
                              >
                                {deploymentAction === `rollback:${item.target.snapshotId}` ? "回滚中…" : "回滚到此快照"}
                              </button>
                            )}
                          </article>
                        );
                      })}
                      {deployments.length === 0 && <p>发布后会在此保留快照、操作者、状态和差异。</p>}
                    </div>
                  </details>
                </section>
                <AgentTriggerControlPlane
                  agentName={draft.name}
                  publishedVersion={draft.publishedVersion}
                  environments={environments}
                  canManage={canPublish}
                />
              </section>
            )}
          </fieldset>
        </div>

        <footer className={styles.editorFooter}>
          <span className={conflict || versionConflict || notice.includes("阻塞") ? styles.noticeError : styles.noticeDot} aria-hidden="true" />
          <span title={notice}>{notice}</span>
          <code>{draft.id ? `revision ${draft.revision}` : "unsaved"}</code>
        </footer>
      </section>

      {evalManagerOpen && (
        <div
          className={styles.evalManagerBackdrop}
          onMouseDown={(event) => {
            if (event.target === event.currentTarget) setEvalManagerOpen(false);
          }}
        >
          <div
            ref={evalManagerRef}
            className={styles.evalManager}
            role="dialog"
            aria-modal="true"
            aria-labelledby="eval-manager-title"
          >
            <header>
              <div>
                <span>EVAL DATASET</span>
                <h2 id="eval-manager-title">评测集管理器</h2>
                <p>编辑场景，或从 JSON、CSV、Excel 批量导入；保存 Agent 草稿后即可固化 Dataset 版本。</p>
              </div>
              <button
                ref={evalManagerCloseRef}
                type="button"
                aria-label="关闭评测集管理器"
                onClick={() => setEvalManagerOpen(false)}
              >
                ×
              </button>
            </header>
            <div className={styles.evalImportBar}>
              <div>
                <strong>批量导入评测场景</strong>
                <span>首行使用 id、label、tag、prompt 等字段；支持中文列名。</span>
              </div>
              <input
                ref={evalImportInputRef}
                hidden
                type="file"
                accept=".json,.csv,.xlsx,application/json,text/csv,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                onChange={(event) => {
                  const file = event.currentTarget.files?.[0];
                  if (file) void importEvalDataset(file);
                }}
              />
              <button
                type="button"
                disabled={!canEdit || evalImporting}
                onClick={() => evalImportInputRef.current?.click()}
              >
                {evalImporting ? "解析中…" : "导入 JSON / CSV / Excel"}
              </button>
            </div>
            {evalImportPreview && (
              <section className={styles.evalImportPreview} aria-label="导入预览">
                <div>
                  <strong>{evalImportPreview.fileName}</strong>
                  <span>{evalImportPreview.cases.length} 条有效 · {evalImportPreview.errors.length} 条需修正</span>
                  {evalImportPreview.errors.length > 0 && (
                    <small>{evalImportPreview.errors.slice(0, 4).join("；")}</small>
                  )}
                </div>
                <button type="button" onClick={() => setEvalImportPreview(null)}>取消</button>
                <button
                  type="button"
                  disabled={!evalImportPreview.cases.length}
                  onClick={confirmEvalDatasetImport}
                >
                  确认追加
                </button>
              </section>
            )}
            <div className={styles.evalManagerToolbar}>
              <span>当前 {draft.evalCases.length} 条</span>
              <button type="button" disabled={!canEdit} onClick={addEvalCase}>新增场景</button>
            </div>
            <div className={styles.evalManagerList}>
              {draft.evalCases.map((testCase, index) => (
                <article key={testCase.id} className={styles.evalCase}>
                  <select
                    aria-label={`${testCase.id} 场景类型`}
                    value={testCase.tag}
                    disabled={!canEdit}
                    onChange={(event) => updateEvalCase(index, {
                      tag: event.target.value as StudioEvalCase["tag"],
                    })}
                  >
                    <option value="happy">正常 happy</option>
                    <option value="ambiguous">歧义 ambiguous</option>
                    <option value="safety">安全 safety</option>
                  </select>
                  <div className={styles.evalCaseEditor}>
                    <input
                      aria-label={`${testCase.id} 名称`}
                      value={testCase.label}
                      disabled={!canEdit}
                      onChange={(event) => updateEvalCase(index, { label: event.target.value })}
                    />
                    <textarea
                      aria-label={`${testCase.id} 提示词`}
                      value={testCase.prompt}
                      disabled={!canEdit}
                      onChange={(event) => updateEvalCase(index, { prompt: event.target.value })}
                    />
                    <details className={styles.evalExpectationEditor}>
                      <summary>断言与运行边界</summary>
                      <div>
                        <label>必须调用<input value={testCase.expect.requiredTools.join(", ")} disabled={!canEdit} onChange={(event) => updateEvalCase(index, { expect: { ...testCase.expect, requiredTools: event.target.value.split(",").map((value) => value.trim()).filter(Boolean) } })} /></label>
                        <label>禁止调用<input value={testCase.expect.forbiddenTools.join(", ")} disabled={!canEdit} onChange={(event) => updateEvalCase(index, { expect: { ...testCase.expect, forbiddenTools: event.target.value.split(",").map((value) => value.trim()).filter(Boolean) } })} /></label>
                        <label>输出包含<input value={testCase.expect.outputContains.join(", ")} disabled={!canEdit} onChange={(event) => updateEvalCase(index, { expect: { ...testCase.expect, outputContains: event.target.value.split(",").map((value) => value.trim()).filter(Boolean) } })} /></label>
                        <label>最大耗时（秒）<input type="number" min={1} value={testCase.expect.maxDurationSeconds} disabled={!canEdit} onChange={(event) => updateEvalCase(index, { expect: { ...testCase.expect, maxDurationSeconds: Math.max(1, Number(event.target.value) || 1) } })} /></label>
                        <label className={styles.evalApprovalCheck}><input type="checkbox" checked={testCase.expect.approvalRequired} disabled={!canEdit} onChange={(event) => updateEvalCase(index, { expect: { ...testCase.expect, approvalRequired: event.target.checked } })} />必须经过审批</label>
                      </div>
                    </details>
                  </div>
                  <div className={styles.evalCaseActions}>
                    <code>{testCase.id}</code>
                    <button type="button" disabled={!canEdit || draft.evalCases.length <= 1} onClick={() => removeEvalCase(index)}>删除</button>
                  </div>
                </article>
              ))}
            </div>
            <footer>
              <span>修改会进入当前 Agent 草稿，尚未固化为 Dataset。</span>
              <button type="button" onClick={() => setEvalManagerOpen(false)}>完成</button>
            </footer>
          </div>
        </div>
      )}

      {contractOpen && (
        <button
          type="button"
          className={styles.contractBackdrop}
          aria-label="关闭有效运行契约"
          onClick={() => setContractOpen(false)}
        />
      )}
      {versionHistoryOpen && (
        <button
          type="button"
          className={styles.contractBackdrop}
          aria-label="关闭版本历史"
          onClick={() => {
            setVersionHistoryOpen(false);
            setPromoteTarget("");
          }}
        />
      )}
      <aside
        ref={versionHistoryRailRef}
        id="personal-version-history"
        className={`${styles.contractRail} ${styles.versionHistoryRail}`}
        aria-label="个人智能体版本历史"
        role="dialog"
        aria-modal="true"
        aria-hidden={!versionHistoryOpen}
        data-open={versionHistoryOpen}
      >
        <div className={styles.contractHeader}>
          <div>
            <span>IMMUTABLE RELEASES</span>
            <strong>版本历史</strong>
          </div>
          <div className={styles.contractHeaderActions}>
            <span className={styles.riskBadge}>
              {personalVersions.length} 个版本
            </span>
            <button
              type="button"
              ref={versionHistoryCloseRef}
              aria-label="关闭版本历史"
              onClick={() => {
                setVersionHistoryOpen(false);
                setPromoteTarget("");
              }}
            >
              ×
            </button>
          </div>
        </div>

        <section className={styles.versionHistoryIntro}>
          <span>当前运行指针</span>
          <strong>{draft.name}@{currentPersonalVersion ?? "尚未发布"}</strong>
          <p>切换只影响之后创建的任务。历史版本、已有任务和运行中的 Session 保持原绑定。</p>
        </section>

        {versionHistoryLoading && (
          <div className={styles.versionHistoryState} role="status">
            正在读取不可变版本…
          </div>
        )}
        {versionHistoryError && (
          <div className={styles.versionHistoryError} role="alert">
            <strong>版本历史暂时不可用</strong>
            <span>{versionHistoryError}</span>
            {draft.agentId && (
              <button
                type="button"
                onClick={() => {
                  setVersionHistoryError("");
                  setVersionHistoryLoading(true);
                  void studioClient.listPersonalAgentVersions(draft.agentId as string)
                    .then(setPersonalVersions)
                    .catch((error: unknown) => setVersionHistoryError(
                      error instanceof Error ? error.message : "版本历史暂时不可用",
                    ))
                    .finally(() => setVersionHistoryLoading(false));
                }}
              >
                重新加载
              </button>
            )}
          </div>
        )}

        {!versionHistoryLoading && !versionHistoryError && (
          <ol className={styles.versionTimeline}>
            {personalVersions.map((item, index) => {
              const current = item.version === item.current_version;
              const confirming = promoteTarget === item.version;
              return (
                <li key={item.version} data-current={current}>
                  <span className={styles.versionSequence} aria-hidden="true">
                    {String(personalVersions.length - index).padStart(2, "0")}
                  </span>
                  <article>
                    <header>
                      <div>
                        <strong>{item.version}</strong>
                        {current && <em>当前</em>}
                      </div>
                      <time dateTime={item.created_at}>
                        {new Date(item.created_at).toLocaleString("zh-CN", {
                          month: "2-digit",
                          day: "2-digit",
                          hour: "2-digit",
                          minute: "2-digit",
                        })}
                      </time>
                    </header>
                    <dl>
                      <div><dt>内容</dt><dd>{item.manifest_hash.slice(0, 12)}</dd></div>
                      <div><dt>Bundle</dt><dd>{item.package_hash?.slice(0, 12) ?? "未记录"}</dd></div>
                    </dl>
                    {current ? (
                      <p className={styles.versionCurrentNote}>新任务默认使用这个版本</p>
                    ) : confirming ? (
                      <div className={styles.versionPromoteConfirm} role="group" aria-label={`确认切换到 ${item.version}`}>
                        <p>将新任务切换到 {item.version}？已有任务不会改变。</p>
                        <div>
                          <button
                            type="button"
                            disabled={Boolean(promotingVersion)}
                            onClick={() => void promotePersonalVersion(item.version)}
                          >
                            {promotingVersion === item.version ? "切换中…" : "确认切换"}
                          </button>
                          <button
                            type="button"
                            disabled={Boolean(promotingVersion)}
                            onClick={() => setPromoteTarget("")}
                          >
                            取消
                          </button>
                        </div>
                      </div>
                    ) : (
                      <button
                        type="button"
                        className={styles.versionPromoteButton}
                        disabled={!canPublish || Boolean(promotingVersion)}
                        onClick={() => setPromoteTarget(item.version)}
                      >
                        设为当前版本
                      </button>
                    )}
                  </article>
                </li>
              );
            })}
            {personalVersions.length === 0 && (
              <li className={styles.versionHistoryEmpty}>还没有可切换的发布版本。</li>
            )}
          </ol>
        )}

        <footer className={styles.versionHistoryFootnote}>
          回退是移动当前指针，不会修改或删除任何不可变版本。
        </footer>
      </aside>
      <aside
        ref={contractRailRef}
        id="effective-contract-drawer"
        className={styles.contractRail}
        aria-label="有效运行契约"
        role="dialog"
        aria-modal="true"
        aria-hidden={!contractOpen}
        data-open={contractOpen}
      >
        <div className={styles.contractHeader}>
          <div>
            <span>有效运行契约</span>
            <strong>{contract.ready ? "结构就绪" : "需要处理"}</strong>
          </div>
          <div className={styles.contractHeaderActions}>
            <span className={styles.riskBadge} data-risk={contract.risk}>
              风险 {riskLabel(contract.risk)}
            </span>
            <button
              type="button"
              ref={contractCloseRef}
              aria-label="关闭有效运行契约"
              onClick={() => setContractOpen(false)}
            >
              ×
            </button>
          </div>
        </div>

        <div className={styles.capabilitySpine}>
          <ContractNode
            index="M"
            label="Model"
            value={contract.model}
            detail={contract.routeLabel}
            state="ready"
          />
          <ContractNode
            index="P"
            label="Prompt"
            value={`${contract.promptSections} / 5 章节`}
            detail="稳定行为契约"
            state={contract.promptSections === 5 ? "ready" : "error"}
          />
          <ContractNode
            index="S"
            label="Skills"
            value={`${contract.skillCount} 个领域工作流`}
            detail={draft.skills.map((item) => item.name).join(", ")}
            state={contract.skillCount > 0 ? "ready" : "error"}
          />
          <ContractNode
            index="T"
            label="Tools"
            value={`${contract.toolCount} 项能力`}
            detail={`${contract.networkLabel} · ${contract.approvalLabel}`}
            state="ready"
          />
          <ContractNode
            index="A"
            label="Agents"
            value={contract.collaborationLabel}
            detail={
              contract.subagentCount > 0
                ? `${contract.backgroundSubagentCount} 个角色允许后台并行`
                : "未启用 Task 委派"
            }
            state={
              draft.builtinTools.includes("Task") === (contract.subagentCount > 0)
                ? "ready"
                : "error"
            }
          />
          <ContractNode
            index="I"
            label="Isolation"
            value={contract.sandboxLabel}
            detail="独立身份 · Provider 由执行档位决定"
            state="locked"
          />
          <ContractNode
            index="R"
            label="Release"
            value={
              publishedCurrent
                ? `已发布 ${draft.name}@${draft.publishedVersion}`
                : contract.ready
                  ? "可生成不可变 Bundle"
                  : "配置未通过"
            }
            detail={publishedCurrent ? `hash ${draft.publishedHash?.slice(0, 12)}` : "发布后版本不可覆盖"}
            state={publishedCurrent || contract.ready ? "ready" : "error"}
          />
        </div>

        <section className={styles.contractFacts}>
          <h2>边界摘要</h2>
          <dl>
            <div><dt>联网</dt><dd>{contract.networkLabel}</dd></div>
            <div><dt>文件</dt><dd>{draft.builtinTools.includes("Write") ? "可在沙箱生成" : "只读"}</dd></div>
            <div><dt>命令</dt><dd>{draft.builtinTools.includes("Bash") ? "启用 · 沙箱安全命令自动执行" : "未启用"}</dd></div>
            <div>
              <dt>协同</dt>
              <dd>{contract.collaborationLabel}</dd>
            </div>
            <div>
              <dt>Sub 角色</dt>
              <dd>
                {draft.subagents.length
                  ? draft.subagents.map((subagent) => subagent.alias).join(", ")
                  : "无"}
              </dd>
            </div>
            <div><dt>会话</dt><dd>{draft.restoreSession ? "允许恢复" : "每轮新建"}</dd></div>
            <div><dt>归档</dt><dd>{draft.archiveOnComplete ? "运行结束归档" : "按 TTL 回收"}</dd></div>
            <div><dt>身份</dt><dd>发布版本独立工作负载身份</dd></div>
            <div><dt>运行限额</dt><dd>轮次、Token、预算与 Sub Usage 不限</dd></div>
          </dl>
        </section>

        {inspected && (
          <section className={contract.ready ? styles.validationReady : styles.validationIssues} role="status">
            <strong>{validationReady ? "结构检查通过" : "发布被阻止"}</strong>
            {validationReady ? (
              <p>Manifest、Prompt、Skills、工具与评测覆盖已通过服务端编译前条件。</p>
            ) : (
              <ul>
                {(serverValidation?.issues.map(validationIssueMessage) ?? contract.issues)
                  .map((issue) => <li key={issue}>{issue}</li>)}
              </ul>
            )}
          </section>
        )}

        <p className={styles.contractFootnote}>
          页面不保存 Endpoint、Token 或任意 MCP URL。凭据只在运行时按租户与执行身份注入。
        </p>
      </aside>
      {confirmationDialog}
    </main>
  );
}

function PanelHeading({
  id,
  kicker,
  title,
  description,
}: {
  id: string;
  kicker: string;
  title: string;
  description: string;
}) {
  return (
    <header className={styles.panelHeading}>
      <span>{kicker}</span>
      <h2 id={id}>{title}</h2>
      <p>{description}</p>
    </header>
  );
}

function PythonCodeEditor({
  value,
  onChange,
}: {
  value: string;
  onChange: (value: string) => void;
}) {
  const exportsRun = /^\s*def\s+run\s*\(\s*arguments\s*\)/m.test(value);

  return (
    <StudioCodeEditor
      ariaLabel="Python 源码"
      filename="tool.py"
      language="python"
      runtimeLabel="Python 3.12 · Sandbox"
      status={exportsRun ? "run(arguments) 已识别" : "缺少 run(arguments)"}
      statusTone={exportsRun ? "ready" : "error"}
      value={value}
      onChange={onChange}
    />
  );
}

function validateJsonSchema(source: string): {
  parsed?: Record<string, unknown>;
  status: string;
  tone: "ready" | "error";
} {
  try {
    const parsed = JSON.parse(source) as unknown;
    if (!parsed || Array.isArray(parsed) || typeof parsed !== "object") {
      return { status: "根节点必须是对象", tone: "error" };
    }
    return {
      parsed: parsed as Record<string, unknown>,
      status: "JSON 有效",
      tone: "ready",
    };
  } catch (error) {
    const message = error instanceof Error ? error.message : "JSON 语法错误";
    return {
      status: message.replace(/^JSON\.parse:\s*/i, "").slice(0, 72),
      tone: "error",
    };
  }
}

function JsonSchemaCodeEditor({
  value,
  onCommit,
  onInvalid,
}: {
  value: Record<string, unknown>;
  onCommit: (value: Record<string, unknown>) => void;
  onInvalid: (message: string) => void;
}) {
  const [source, setSource] = useState(() => JSON.stringify(value, null, 2));
  const validation = useMemo(() => validateJsonSchema(source), [source]);
  const fieldCount = Object.keys(
    (value.properties as object | undefined) ?? {},
  ).length;

  function commit(next: string) {
    const result = validateJsonSchema(next);
    if (result.parsed) {
      onCommit(result.parsed);
      return;
    }
    onInvalid(result.status);
  }

  return (
    <StudioCodeEditor
      ariaLabel="JSON Schema"
      filename="input.schema.json"
      language="json"
      runtimeLabel={`JSON Schema · ${fieldCount} fields`}
      status={validation.status}
      statusTone={validation.tone}
      value={source}
      onChange={setSource}
      onBlur={commit}
    />
  );
}

function Field({
  label,
  hint,
  wide = false,
  children,
}: {
  label: string;
  hint?: string;
  wide?: boolean;
  children: React.ReactNode;
}) {
  return (
    <label className={wide ? styles.fieldWide : styles.field}>
      <span>{label}{hint && <small>{hint}</small>}</span>
      {children}
    </label>
  );
}

function InfoStrip({
  tone,
  children,
}: {
  tone: "neutral" | "warning";
  children: React.ReactNode;
}) {
  return <div className={tone === "warning" ? styles.warningStrip : styles.infoStrip}>{children}</div>;
}

function ContractNode({
  index,
  label,
  value,
  detail,
  state,
}: {
  index: string;
  label: string;
  value: string;
  detail: string;
  state: "ready" | "error" | "locked";
}) {
  return (
    <div className={styles.contractNode} data-state={state}>
      <span className={styles.nodeIndex}>{index}</span>
      <div>
        <span>{label}</span>
        <strong>{value}</strong>
        <small>{detail}</small>
      </div>
    </div>
  );
}
