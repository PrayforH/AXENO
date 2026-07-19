"use client";

import { useEffect, useMemo, useRef, useState, type KeyboardEvent } from "react";
import { useAuth } from "../auth-provider";
import { StudioSidebar } from "./studio-sidebar";
import {
  DEFAULT_STUDIO_DRAFT,
  REQUIRED_PROMPT_HEADINGS,
  evaluateStudioDraft,
  type StudioDraft,
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
  type StudioEvalDataset,
  type StudioEvalGate,
  type StudioEvalRun,
  type StudioPreflightCheck,
  type StudioPreview,
  type StudioQualityGate,
  type StudioQualityIncident,
  type StudioQualityRule,
  type StudioQualityScore,
  type StudioValidation,
} from "../../lib/studio-client";
import { migrateLegacyStudioDraft } from "../../lib/studio-migration";
import { AgentTriggerControlPlane } from "./agent-trigger-control-plane";
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

const preflightStageLabels = {
  bundle: "不可变 Bundle",
  sandbox_provision: "Sandbox 创建",
  sandbox_prepare: "Workspace 准备",
  model: "模型流式与 Tool Use",
  mcp: "MCP 与只读 Smoke",
  approval: "Write / Edit / Bash 审批",
  workspace_artifact: "文件与 Artifact",
  cleanup: "Sandbox 清理",
} as const;

const preflightErrorLabels: Record<string, string> = {
  execution_profile_sandbox_provider_mismatch:
    "当前 Preview Sandbox 与所选执行档位不一致。Local 模式请选择“本地开发 Preview”，保存并重新检查后再试。",
};

function preflightProgress(checks: StudioPreflightCheck[]) {
  const passed = checks.filter((check) => check.status === "passed").length;
  const skipped = checks.filter((check) => check.status === "skipped").length;
  return skipped > 0
    ? `${passed} 通过 · ${skipped} 跳过`
    : `${passed}/${checks.length} 通过`;
}

export function AgentStudioWorkbench() {
  const { membership } = useAuth();
  const [draft, setDraft] = useState<StudioDraft>({
    ...DEFAULT_STUDIO_DRAFT,
    id: "",
    revision: 0,
  });
  const [drafts, setDrafts] = useState<StudioDraftSummary[]>([]);
  const [capabilities, setCapabilities] = useState<StudioCapabilities | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState("");
  const [saving, setSaving] = useState(false);
  const [publishing, setPublishing] = useState(false);
  const [creatingPreview, setCreatingPreview] = useState(false);
  const [previews, setPreviews] = useState<StudioPreview[]>([]);
  const [evalDatasets, setEvalDatasets] = useState<StudioEvalDataset[]>([]);
  const [evalRuns, setEvalRuns] = useState<StudioEvalRun[]>([]);
  const [evalGate, setEvalGate] = useState<StudioEvalGate | null>(null);
  const [evalAction, setEvalAction] = useState<"dataset" | "run" | "cancel" | "">("");
  const [environments, setEnvironments] = useState<StudioEnvironment[]>([]);
  const [deployments, setDeployments] = useState<StudioDeployment[]>([]);
  const [deploymentSnapshots, setDeploymentSnapshots] = useState<StudioDeploymentSnapshot[]>([]);
  const [deploymentAction, setDeploymentAction] = useState("");
  const [qualityScores, setQualityScores] = useState<StudioQualityScore[]>([]);
  const [qualityIncidents, setQualityIncidents] = useState<StudioQualityIncident[]>([]);
  const [qualityRules, setQualityRules] = useState<StudioQualityRule[]>([]);
  const [qualityGate, setQualityGate] = useState<StudioQualityGate | null>(null);
  const [dirty, setDirty] = useState(false);
  const [conflict, setConflict] = useState(false);
  const [versionConflict, setVersionConflict] = useState(false);
  const [serverValidation, setServerValidation] = useState<StudioValidation | null>(null);
  const [activeSection, setActiveSection] =
    useState<StudioSection>("capabilities");
  const [agentQuery, setAgentQuery] = useState("");
  const [inspected, setInspected] = useState(false);
  const [promptFocusMode, setPromptFocusMode] = useState(false);
  const [notice, setNotice] = useState("正在读取控制面草稿…");
  const promptEditorRef = useRef<HTMLTextAreaElement>(null);
  const canEdit = membership.role !== "viewer";
  const canPublish = membership.role === "owner" || membership.role === "admin";
  const options = useMemo(
    () => capabilities
      ? capabilityOptions(capabilities)
      : { routes: [], tools: [], mcp: [], profiles: [] },
    [capabilities],
  );
  const contract = useMemo(
    () => evaluateStudioDraft(draft, { routes: options.routes, mcp: options.mcp }),
    [draft, options],
  );
  const policyOptions = useMemo(
    () => capabilities?.policies.filter((item) => item.enabled).map((item) => ({
      id: item.policyId,
      label: item.label,
      description: item.description,
    })) ?? [],
    [capabilities],
  );
  const publishedSubagents = useMemo(
    () => drafts
      .filter((item) => item.publishedVersion)
      .map((item) => ({
        ref: `${item.name}@${item.publishedVersion}`,
        label: item.displayName,
        description: `${item.domain} · 已发布租户版本`,
        policy: "已发布快照",
        tools: [] as string[],
        status: "approved" as const,
      })),
    [drafts],
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
    let active = true;
    async function load() {
      setLoading(true);
      setLoadError("");
      try {
        const [serverDrafts, serverCapabilities, serverPreviews, serverDatasets, serverEvalRuns] = await Promise.all([
          studioClient.listDrafts(),
          studioClient.capabilities(),
          studioClient.listPreviews(),
          studioClient.listEvalDatasets(),
          studioClient.listEvalRuns(),
        ]);
        if (!active) return;
        setCapabilities(serverCapabilities);
        setDrafts(serverDrafts);
        setPreviews(serverPreviews);
        setEvalDatasets(serverDatasets);
        setEvalRuns(serverEvalRuns);
        const migration = await migrateLegacyStudioDraft(
          window.localStorage,
          studioClient,
          canEdit,
        );
        if (!active) return;
        if (migration.status === "imported") {
          setDraft(migration.draft);
          setDrafts(await studioClient.listDrafts());
          setNotice("旧浏览器草稿已一次性导入控制面");
        } else if (serverDrafts.length > 0) {
          const selected = await studioClient.getDraft(serverDrafts[0].draftId);
          if (!active) return;
          setDraft(apiDraftToStudioDraft(selected));
          setNotice("已从控制面加载草稿");
        } else {
          setDraft({ ...DEFAULT_STUDIO_DRAFT, id: "", revision: 0 });
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
    setDraft((current) => ({ ...current, ...update }));
    setInspected(false);
    setServerValidation(null);
    setDirty(true);
    setConflict(false);
    setVersionConflict(false);
    setNotice("有尚未保存的修改");
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
    const published = publishedSubagents[0];
    if (!published) {
      setNotice("当前租户没有可绑定的已发布 Agent 版本");
      return;
    }
    const sequence = draft.subagents.length + 1;
    updateDraft({
      subagents: [
        ...draft.subagents,
        {
          alias: `specialist-${sequence}`,
          ref: published.ref,
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

  async function saveDraft(): Promise<StudioDraft | null> {
    if (!canEdit) {
      setNotice("当前角色只有查看权限");
      return null;
    }
    setSaving(true);
    try {
      let saved;
      if (!draft.id) {
        const created = await studioClient.createDraft(draft);
        saved = await studioClient.replaceDraft({
          ...draft,
          id: created.draftId,
          revision: created.revision,
        });
      } else {
        saved = await studioClient.replaceDraft(draft);
      }
      const next = apiDraftToStudioDraft(saved);
      setDraft(next);
      setDrafts(await studioClient.listDrafts());
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

  async function inspectDraft() {
    const current = dirty || !draft.id ? await saveDraft() : draft;
    if (!current?.id) return;
    try {
      const validation = await studioClient.validateDraft(current.id);
      setServerValidation(validation);
      setInspected(true);
      setNotice(validation.ready ? "服务端结构检查通过" : `发现 ${validation.issues.length} 个问题`);
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "检查失败");
    }
  }

  async function selectDraft(draftId: string) {
    if (dirty && !window.confirm("当前修改尚未保存，仍要切换草稿吗？")) return;
    try {
      const selected = await studioClient.getDraft(draftId);
      setDraft(apiDraftToStudioDraft(selected));
      setDirty(false);
      setConflict(false);
      setVersionConflict(false);
      setServerValidation(null);
      setNotice("已从控制面切换草稿");
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "加载草稿失败");
    }
  }

  async function reloadAfterConflict() {
    if (!draft.id) return;
    const selected = await studioClient.getDraft(draft.id);
    setDraft(apiDraftToStudioDraft(selected));
    setDirty(false);
    setConflict(false);
    setVersionConflict(false);
    setNotice("已加载控制面最新 revision");
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

  async function publishDraft() {
    if (!draft.id || dirty || !serverValidation?.ready || !canPublish) return;
    setPublishing(true);
    try {
      const version = await studioClient.publishDraft(draft.id, draft.revision);
      const [refreshed, rows] = await Promise.all([
        studioClient.getDraft(draft.id),
        studioClient.listDrafts(),
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
        crypto.randomUUID(),
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
    if (!draft.id || dirty || !canEdit) return;
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
        `studio-eval:${dataset.datasetId}:v${dataset.version}:${draft.publishedVersion}:${crypto.randomUUID()}`,
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
        return `${draft.evalCases.length} 用例`;
    }
  }

  const selectedRoute =
    options.routes.find((route) => route.id === draft.modelRoute) ?? options.routes[0];
  const skill = draft.skills[0];
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
  const snapshotById = new Map(
    deploymentSnapshots.map((snapshot) => [snapshot.snapshotId, snapshot]),
  );
  const activeDeployment = deployments.find((item) =>
    ["queued", "reconciling"].includes(item.deployment.status),
  );
  const latestQualityScores = Array.from(
    new Map(qualityScores.map((score) => [score.name, score])).values(),
  );
  const openQualityIncidents = qualityIncidents.filter(
    (incident) => incident.state === "open",
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
      setQualityScores([]);
      setQualityIncidents([]);
      setQualityRules([]);
      setQualityGate(null);
      return;
    }
    let active = true;
    void Promise.all([
      studioClient.listQualityScores(draft.name),
      studioClient.listQualityIncidents(draft.name),
      studioClient.listQualityRules(draft.name),
      studioClient.getQualityGate(draft.name, draft.publishedVersion),
    ]).then(([scores, incidents, rules, gate]) => {
      if (!active) return;
      setQualityScores(scores);
      setQualityIncidents(incidents);
      setQualityRules(rules);
      setQualityGate(gate);
    }).catch(() => {
      if (active) setQualityGate(null);
    });
    return () => { active = false; };
  }, [draft.id, draft.name, draft.publishedVersion]);

  if (loading) {
    return <main className={styles.studioStateShell} id="main-content" aria-busy="true"><section className={styles.studioStateCard}><span className={styles.studioStateMark}>AS</span><h1>正在读取 Agent Studio</h1><p>从控制面恢复租户草稿与能力目录。</p></section></main>;
  }
  if (loadError) {
    return <main className={styles.studioStateShell} id="main-content"><section className={styles.studioStateCard} role="alert"><span className={styles.studioStateMark}>!</span><h1>Agent Studio 数据暂不可用</h1><p>{loadError}</p><button type="button" onClick={() => window.location.reload()}>重新加载</button></section></main>;
  }

  return (
    <main className={styles.studioShell} id="main-content" data-studio-integration="api">
      <StudioSidebar active="agents">
        <div className={styles.railHeading}>
          <span>智能体目录</span>
          <button
            type="button"
            aria-label="新建智能体"
            disabled={!canEdit}
            onClick={() => {
              setDraft({ ...DEFAULT_STUDIO_DRAFT, id: "", revision: 0 });
              setDirty(true);
              setConflict(false);
              setVersionConflict(false);
              setNotice("新草稿尚未保存到控制面");
            }}
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
              onClick={() => void selectDraft(agent.draftId)}
            >
              <span className={styles.agentMonogram} aria-hidden="true">
                {agent.displayName.slice(0, 1)}
              </span>
              <span className={styles.agentRowCopy}>
                <strong>{agent.displayName}</strong>
                <small>
                  {agent.version} · {agent.publishedVersion ? `已发布 ${agent.publishedVersion}` : "草稿"} · r{agent.revision}
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
        {drafts.length === 0 && !draft.id && (
          <div className={styles.emptyBanner} role="status">
            <strong>当前租户还没有智能体草稿</strong>
            <span>{canEdit ? "填写模板并保存，即可创建第一个草稿。" : "请联系成员或管理员创建后再查看。"}</span>
          </div>
        )}
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
            {draft.publishedVersion && (
              <div className={styles.publicationBadge} data-current={publishedCurrent}>
                <span>{publishedCurrent ? "不可变版本已发布" : "存在历史发布版本"}</span>
                <code>{draft.name}@{draft.publishedVersion}</code>
                {draft.publishedHash && <code>{draft.publishedHash.slice(0, 12)}</code>}
              </div>
            )}
          </div>
          <div className={styles.headerActions}>
            <span className={styles.syncState} data-dirty={dirty}>
              <i aria-hidden="true" />
              {saving ? "正在保存" : dirty ? "有未保存更改" : `已同步 r${draft.revision}`}
            </span>
            <div className={styles.actionGroup}>
              <button type="button" className={styles.secondaryButton} disabled={!canEdit || saving || !dirty} onClick={() => void saveDraft()}>
                <svg viewBox="0 0 20 20" aria-hidden="true"><path d="M5 3.5h8l2 2v11H5zM7.5 3.5v4h5v-4M7.5 13h5" /></svg>
                <span>{saving ? "保存中…" : "保存"}</span>
              </button>
              <button type="button" className={styles.checkButton} disabled={!canEdit || saving} onClick={() => void inspectDraft()}>
                <svg viewBox="0 0 20 20" aria-hidden="true"><path d="m5 10 3 3 7-7" /></svg>
                <span>检查</span>
              </button>
            </div>
            <button
              type="button"
              className={styles.publishButton}
              disabled={!canPublish || !draft.id || dirty || !serverValidation?.ready || publishing}
              title={
                !canPublish
                  ? "当前角色没有发布权限"
                  : dirty
                    ? "请先保存草稿"
                    : !serverValidation?.ready
                      ? "请先通过服务端检查"
                      : "发布为不可覆盖的 Agent 版本"
              }
              onClick={() => void publishDraft()}
            >
              {publishing ? "发布中…" : publishedCurrent ? "重新核验发布" : "发布"}
            </button>
            <details className={styles.actionMenu}>
              <summary aria-label="更多智能体操作" title="更多操作">
                <span aria-hidden="true">•••</span>
              </summary>
              <div className={styles.actionMenuPopover}>
                <button
                  type="button"
                  className={styles.previewButton}
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
                  className={styles.secondaryButton}
                  disabled={!draft.id || saving}
                  onClick={(event) => {
                    event.currentTarget.closest("details")?.removeAttribute("open");
                    void downloadBundle();
                  }}
                >
                  <span><strong>下载 Bundle</strong><small>获取当前不可变配置包</small></span>
                </button>
              </div>
            </details>
          </div>
        </header>

        {conflict && (
          <div className={styles.conflictBanner} role="alert">
            <div><strong>控制面已有更新</strong><span>本地修改仍保留。加载最新 revision 后再重新编辑。</span></div>
            <button type="button" onClick={() => void reloadAfterConflict()}>加载最新版本</button>
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
        {activePreview && (
          <div className={styles.previewBanner} data-status={activePreview.status} data-stale={activePreview.stale}>
            <div className={styles.previewIdentity}>
              <strong>Preview · {activePreview.status}{activePreview.stale ? " · stale" : ""}</strong>
              <span>
                测试身份 · Draft r{activePreview.draftRevision} · 到期 {new Date(activePreview.expiresAt).toLocaleString("zh-CN")}
              </span>
            </div>
            <div className={styles.previewActions}>
              <button type="button" onClick={() => void refreshPreview(activePreview.previewId)}>刷新</button>
              {!(["cancelled", "failed", "expired"] as string[]).includes(activePreview.status) && (
                <button type="button" onClick={() => void cancelPreview(activePreview.previewId)}>取消</button>
              )}
            </div>
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
                    {preflightErrorLabels[activePreview.preflightResult.errorCode]
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
            <strong>{lifecycleStages[activeLifecycleIndex]?.label}</strong>
            <small>{lifecycleStages[activeLifecycleIndex]?.detail}</small>
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
                  <Field label="版本">
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
                  description="Lead 是唯一面向用户的主线；Sub Agent 使用固定版本、独立职责和自己的权限上限，通过 Task 返回可验收结果。"
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
                      <span>添加已发布的 Sub Agent 后，Lead 才能使用 Task 委派。</span>
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
                    const catalogAgent = publishedSubagents.find(
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
                        <Field label="固定版本引用" hint="从已发布目录选择">
                          <select
                            className={styles.monoInput}
                            value={subagent.ref}
                            onChange={(event) => updateSubagent(index, { ref: event.target.value })}
                          >
                            {!publishedSubagents.some((agent) => agent.ref === subagent.ref) && (
                              <option value={subagent.ref}>{subagent.ref || "未识别版本"}</option>
                            )}
                            {publishedSubagents.map((agent) => (
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
                            {catalogAgent.status === "approved" ? "目录已审批" : "目录已弃用"}
                          </span>
                          <div>
                            <strong>{catalogAgent.label}</strong>
                            <small>{catalogAgent.description}</small>
                          </div>
                          <code>{catalogAgent.policy} · {catalogAgent.tools.join(" / ")}</code>
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
                  每个 Sub Agent 继承自己的 Prompt、Skills、Builtin Tools、Policy 和轮次上限。当前运行时不向 Sub Agent 注入 MCP 或 Python Tool；需要联网的证据先由 Lead 收集到共享沙箱。
                </InfoStrip>
              </section>
            )}

            {activeSection === "skills" && skill && (
              <section className={styles.configPanel} aria-labelledby="skills-title">
                <PanelHeading
                  id="skills-title"
                  kicker="05 / Skills"
                  title="沉淀可复用的领域工作流"
                  description="发布时 Skill 及 references、scripts、assets 会一同进入不可变快照。"
                />
                <div className={styles.skillHeader}>
                  <span className={styles.skillGlyph} aria-hidden="true">S</span>
                  <div>
                    <strong>{skill.name}</strong>
                    <span>Agent 内置 Skill · 随版本发布</span>
                  </div>
                  <button type="button" onClick={() => setNotice("Skill 模板库将在目录 API 接入后启用")}>从模板添加</button>
                </div>
                <div className={styles.formGridSingle}>
                  <Field label="Skill 描述">
                    <input
                      value={skill.description}
                      onChange={(event) =>
                        updateDraft({
                          skills: [{ ...skill, description: event.target.value }],
                        })
                      }
                    />
                  </Field>
                  <Field label="工作流说明">
                    <textarea
                      rows={10}
                      value={skill.instructions}
                      onChange={(event) =>
                        updateDraft({
                          skills: [{ ...skill, instructions: event.target.value }],
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
                    <span>{skill.files?.length ?? 0} 个文件</span>
                  </div>
                  {(skill.files ?? []).map((file, index) => (
                    <article className={styles.skillFileCard} key={file.path}>
                      <code>{file.path}</code>
                      <textarea
                        aria-label={`编辑 ${file.path}`}
                        rows={8}
                        value={file.content}
                        onChange={(event) =>
                          updateDraft({
                            skills: [{
                              ...skill,
                              files: (skill.files ?? []).map((candidate, fileIndex) =>
                                fileIndex === index
                                  ? { ...candidate, content: event.target.value }
                                  : candidate,
                              ),
                            }],
                          })
                        }
                      />
                    </article>
                  ))}
                  {(skill.files?.length ?? 0) === 0 && (
                    <div className={styles.skillFilesEmpty}>
                      当前 Skill 没有 references、scripts 或 assets。
                    </div>
                  )}
                </div>
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
                    <h3>数据与联网能力</h3>
                    <p>通过平台注册的逻辑 MCP，不接受任意 URL 或内联密钥。</p>
                  </div>
                  <span>{draft.mcpServers.length} 项已启用</span>
                </div>
                {options.mcp.map((mcp) => {
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
                  <Field label="最大轮次">
                    <input
                      type="number"
                      min={1}
                      value={draft.maxTurns}
                      onChange={(event) => updateDraft({ maxTurns: Number(event.target.value) })}
                    />
                  </Field>
                  <Field label="超时（秒）">
                    <input
                      type="number"
                      min={1}
                      value={draft.timeoutSeconds}
                      onChange={(event) => updateDraft({ timeoutSeconds: Number(event.target.value) })}
                    />
                  </Field>
                  <Field label="单次预算（USD）">
                    <input
                      type="number"
                      min={0.01}
                      step={0.1}
                      value={draft.maxBudgetUsd}
                      onChange={(event) => updateDraft({ maxBudgetUsd: Number(event.target.value) })}
                    />
                  </Field>
                  <Field label="单次模型 Token 上限">
                    <input
                      type="number"
                      min={1}
                      step={1000}
                      value={draft.maxModelTokens}
                      onChange={(event) => updateDraft({ maxModelTokens: Number(event.target.value) })}
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
                  <Field label="单 Sub Usage 上限">
                    <input
                      type="number"
                      min={1}
                      step={1000}
                      value={draft.maxSubagentUsageUnits}
                      onChange={(event) => updateDraft({ maxSubagentUsageUnits: Number(event.target.value) })}
                    />
                  </Field>
                  <p className={styles.fieldHint}>
                    委派深度固定为 1；Sub 不启用 MCP 或 Python Tool。
                  </p>
                </div>
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
                <div className={styles.evalList}>
                  {draft.evalCases.map((testCase) => (
                    <article key={testCase.id} className={styles.evalCase}>
                      <span data-tag={testCase.tag}>{testCase.tag}</span>
                      <div>
                        <strong>{testCase.label}</strong>
                        <p>{testCase.prompt}</p>
                        <div className={styles.evalAssertions}>
                          <span>终态 {testCase.expect.terminalStatuses.join(" / ")}</span>
                          {testCase.expect.requiredTools.length > 0 && (
                            <span>必须调用 {testCase.expect.requiredTools.join(" / ")}</span>
                          )}
                          {testCase.expect.forbiddenTools.length > 0 && (
                            <span>禁止 {testCase.expect.forbiddenTools.join(" / ")}</span>
                          )}
                          {testCase.expect.outputContains.length > 0 && (
                            <span>输出含 {testCase.expect.outputContains.join(" / ")}</span>
                          )}
                          {testCase.expect.approvalRequired && <span>必须经过审批</span>}
                          <span>≤ {testCase.expect.maxDurationSeconds}s</span>
                        </div>
                      </div>
                      <code>{testCase.id}</code>
                    </article>
                  ))}
                </div>
                <section className={styles.evalControlPlane} aria-label="持久化评测控制面">
                  <header>
                    <div>
                      <span>耐久 Eval 控制面</span>
                      <strong>
                        {latestDataset
                          ? `${latestDataset.name} · v${latestDataset.version}`
                          : "尚未固化 Dataset Version"}
                      </strong>
                      <small>
                        每个 Case 使用独立 Session；进度、Run/Event 评分和报告均由服务端持久化。
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
                            : "固化 Dataset"}
                      </button>
                      <button
                        type="button"
                        disabled={!canEdit || !latestDataset || !draft.publishedVersion || Boolean(evalAction) || Boolean(activeEvalRun && ["queued", "running", "cancelling"].includes(activeEvalRun.run.status))}
                        onClick={() => latestDataset && void startEvalRun(latestDataset)}
                      >
                        {evalAction === "run" ? "排队中…" : "运行固定版本 Eval"}
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
                      固化 Dataset 并发布不可变 Agent 版本后，可启动第一轮耐久 Eval。
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
                <section className={styles.qualityControlPlane} aria-label="线上质量与告警">
                  <header>
                    <div>
                      <span>ONLINE QUALITY</span>
                      <strong>规则 Score、人工反馈与 Alert</strong>
                      <small>Run 终态不依赖 Langfuse；外部同步失败独立重试，Promotion 只读取本地耐久门禁。</small>
                    </div>
                    <em data-state={qualityGate?.passed === false ? "blocked" : "ready"}>
                      {qualityGate?.passed === false
                        ? `${qualityGate.blockingIncidentIds.length} 个阻断告警`
                        : "质量门禁通过"}
                    </em>
                  </header>
                  <div className={styles.qualityScoreGrid}>
                    {latestQualityScores.slice(0, 6).map((score) => (
                      <article key={score.scoreId} data-value={score.value < 0.8 ? "low" : "ok"}>
                        <span>{score.source}</span>
                        <strong>{score.name.replaceAll("_", " ")}</strong>
                        <code>{score.value.toFixed(2)}</code>
                        <small>{score.agentVersion} · Run {score.runId.slice(-8)}</small>
                      </article>
                    ))}
                    {latestQualityScores.length === 0 && (
                      <p>版本部署并产生 Run 后，将在此显示终态、工具、审批、时长、成本和 Artifact Score。</p>
                    )}
                  </div>
                  {openQualityIncidents.length > 0 && (
                    <div className={styles.qualityAlerts}>
                      {openQualityIncidents.map((incident) => {
                        const rule = qualityRules.find((item) => item.ruleId === incident.ruleId);
                        return (
                          <article key={incident.incidentId}>
                            <span>ALERT</span>
                            <div>
                              <strong>{rule?.scoreName ?? incident.ruleId} · {incident.observedValue.toFixed(2)}</strong>
                              <small>{incident.sampleCount} 个样本 · {rule?.blocksPromotion ? "阻断晋级" : "仅告警"}</small>
                            </div>
                            {rule?.dashboardUrl && (
                              <a href={rule.dashboardUrl} target="_blank" rel="noreferrer">查看 Dashboard</a>
                            )}
                          </article>
                        );
                      })}
                    </div>
                  )}
                </section>
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
                    <span>线上质量监控</span>
                    <strong>
                      {qualityGate
                        ? qualityGate.passed
                          ? "规则 / 人工 Score 无阻断告警"
                          : `${qualityGate.blockingIncidentIds.length} 个 Alert 阻断晋级`
                        : "等待版本运行样本"}
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
                              || Boolean(deploymentAction)
                            }
                            onClick={() => void promoteTo(environment)}
                          >
                            {deploymentAction === `promote:${environment.name}`
                              ? "提交中…"
                              : alreadyCurrent
                                ? "当前版本"
                                : environment.name === "canary" && environment.healthySnapshotId
                                  ? "灰度 10% 新会话"
                                  : `发布 ${draft.publishedVersion ?? "版本"}`}
                          </button>
                        </article>
                      );
                    })}
                  </div>
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
          <span>{notice}</span>
          <code>{draft.id ? `revision ${draft.revision}` : "unsaved"}</code>
        </footer>
      </section>

      <aside className={styles.contractRail} aria-label="有效运行契约">
        <div className={styles.contractHeader}>
          <div>
            <span>有效运行契约</span>
            <strong>{contract.ready ? "结构就绪" : "需要处理"}</strong>
          </div>
          <span className={styles.riskBadge} data-risk={contract.risk}>
            风险 {riskLabel(contract.risk)}
          </span>
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
            <div><dt>命令</dt><dd>{draft.builtinTools.includes("Bash") ? "启用 · 默认审批" : "未启用"}</dd></div>
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
            <div><dt>预算</dt><dd>${draft.maxBudgetUsd.toFixed(2)} / Run</dd></div>
          </dl>
        </section>

        {inspected && (
          <section className={contract.ready ? styles.validationReady : styles.validationIssues} role="status">
            <strong>{validationReady ? "结构检查通过" : "发布被阻止"}</strong>
            {validationReady ? (
              <p>Manifest、Prompt、Skills、工具与评测覆盖已通过服务端编译前条件。</p>
            ) : (
              <ul>{(serverValidation?.issues.map((issue) => issue.message) ?? contract.issues).map((issue) => <li key={issue}>{issue}</li>)}</ul>
            )}
          </section>
        )}

        <p className={styles.contractFootnote}>
          页面不保存 Endpoint、Token 或任意 MCP URL。凭据只在运行时按租户与执行身份注入。
        </p>
      </aside>
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
