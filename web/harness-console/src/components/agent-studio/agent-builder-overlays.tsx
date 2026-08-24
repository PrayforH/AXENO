"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import {
  apiDraftToStudioDraft,
  studioClient,
  type StudioAgentBuilderPatch,
  type StudioCapabilities,
  type StudioSolidifiedAgentResult,
  type StudioTaskDrivenRecommendation,
  type StudioTryRun,
} from "../../lib/studio-client";
import { createRandomId } from "../../lib/random-id";
import type { StudioDraft, StudioEvalCase } from "../../lib/agent-studio";
import styles from "./agent-builder-overlays.module.css";

function lines(value: string) {
  return value.split("\n").map((item) => item.trim()).filter(Boolean);
}

export type CreatedAgentFlow = {
  draft: StudioDraft;
  prompt: string;
  recommendation: StudioTaskDrivenRecommendation | null;
  autoRun: boolean;
};

export function NewAgentDialog({
  open,
  templates,
  reservedNames,
  onClose,
  onCreated,
}: {
  open: boolean;
  templates: StudioCapabilities["templates"];
  reservedNames: string[];
  onClose: () => void;
  onCreated: (flow: CreatedAgentFlow) => void;
}) {
  const [displayName, setDisplayName] = useState("");
  const [name, setName] = useState(`agent-${Date.now().toString(36)}`);
  const [domain, setDomain] = useState("general");
  const [task, setTask] = useState("");
  const [sampleInput, setSampleInput] = useState("");
  const [runtimePreference, setRuntimePreference] = useState<"auto" | StudioDraft["runtime"]>("auto");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  if (!open) return null;

  function validIdentity() {
    return Boolean(
      displayName.trim()
      && /^[a-z][a-z0-9-]*$/.test(name.trim())
      && /^[a-z][a-z0-9-]*$/.test(domain.trim()),
    );
  }

  async function createFromTask() {
    if (!validIdentity() || task.trim().length < 8) return;
    if (reservedNames.includes(name.trim())) {
      setError("该 Agent 名称已存在");
      return;
    }
    setBusy(true);
    setError("");
    try {
      const created = await studioClient.createDraftFromTask({
        displayName: displayName.trim(),
        name: name.trim(),
        domain: domain.trim(),
        task: task.trim(),
        sampleInput: sampleInput.trim() || undefined,
        runtimePreference,
      });
      onCreated({
        draft: apiDraftToStudioDraft(created.draft),
        prompt: sampleInput.trim() || task.trim(),
        recommendation: created.recommendation,
        autoRun: true,
      });
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "创建失败");
    } finally {
      setBusy(false);
    }
  }

  async function createFromTemplate(template: StudioDraft["template"]) {
    if (!validIdentity()) {
      setError("请先填写显示名称、Agent name 与领域");
      return;
    }
    if (reservedNames.includes(name.trim())) {
      setError("该 Agent 名称已存在");
      return;
    }
    setBusy(true);
    setError("");
    try {
      const description = task.trim() || templates.find((item) => item.template === template)?.description || "从服务端模板创建的智能体";
      const created = await studioClient.createDraft({
        template,
        displayName: displayName.trim(),
        name: name.trim(),
        domain: domain.trim(),
        description,
      });
      onCreated({
        draft: apiDraftToStudioDraft(created),
        prompt: sampleInput.trim() || task.trim() || description,
        recommendation: null,
        autoRun: false,
      });
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "创建失败");
    } finally {
      setBusy(false);
    }
  }

  return <div className={styles.backdrop} role="presentation">
    <section className={`${styles.dialog} ${styles.builderDialog}`} role="dialog" aria-modal="true" aria-labelledby="new-agent-title">
      <header><div><span>TASK → AGENT</span><h2 id="new-agent-title">描述任务，生成可试跑 Agent</h2></div><button type="button" onClick={onClose}>×</button></header>
      <p>先说清楚要完成什么。Builder 会按租户能力目录推荐运行时、模型、工具、只读 MCP、权限与基础评测，然后立即进入真实试跑。</p>
      <div className={styles.builderLayout}>
        <div className={styles.taskBrief}>
          <label><span>这个 Agent 要完成什么？</span><textarea autoFocus value={task} onChange={(event) => setTask(event.target.value)} placeholder="例如：搜索最新涉非舆情，分析风险，生成一份带证据索引的可下载报告。" /></label>
          <label><span>首次试跑任务 <small>可选；留空时使用上面的任务</small></span><textarea value={sampleInput} onChange={(event) => setSampleInput(event.target.value)} placeholder="例如：分析今天 9:00—12:00 的样本，按风险等级输出报告。" /></label>
        </div>
        <aside className={styles.builderPromise}>
          <span>创建后会自动完成</span>
          <ol><li>编译任务契约</li><li>匹配模型、工具与 MCP</li><li>生成三类基础评测</li><li>启动隔离试跑</li><li>展示 Codex Loop</li></ol>
          <p>只有成功试跑才能固化为不可变版本。</p>
        </aside>
      </div>
      <div className={styles.formGrid}>
        <label><span>显示名称</span><input value={displayName} onChange={(e) => setDisplayName(e.target.value)} placeholder="涉非舆情分析智能体" /></label>
        <label><span>Agent name</span><input value={name} pattern="[a-z][a-z0-9-]*" onChange={(e) => setName(e.target.value)} /></label>
        <label><span>领域</span><input value={domain} pattern="[a-z][a-z0-9-]*" onChange={(e) => setDomain(e.target.value)} /></label>
        <label><span>运行时偏好</span><select value={runtimePreference} onChange={(event) => setRuntimePreference(event.target.value as "auto" | StudioDraft["runtime"])}><option value="auto">自动匹配（优先 Codex）</option><option value="codex-app-server">Codex App Server</option><option value="claude-agent-sdk">Claude Agent SDK</option></select></label>
      </div>
      <details className={styles.templateFallback}>
        <summary>其他创建方式：从服务端模板开始</summary>
        <p>模板只提供通用脚手架，不会自动启动试跑。适合已经知道要手工配置哪些能力的用户。</p>
        <div className={styles.templateGrid}>{templates.map((item) => <button key={item.template} type="button" disabled={busy} onClick={() => void createFromTemplate(item.template)}><strong>{item.label}</strong><small>{item.description}</small><em>直接创建</em></button>)}</div>
      </details>
      {error && <p className={styles.error}>{error}</p>}
      <footer><button type="button" onClick={onClose}>取消</button><button type="button" className={styles.primary} disabled={busy || !validIdentity() || task.trim().length < 8} onClick={() => void createFromTask()}>{busy ? "正在编译 Agent…" : "生成草稿并试跑"}</button></footer>
    </section>
  </div>;
}

export function AgentBuilderCopilot({
  open,
  draft,
  onClose,
  onApply,
}: {
  open: boolean;
  draft: StudioDraft;
  onClose: () => void;
  onApply: (patch: Partial<StudioDraft>) => void;
}) {
  const [goal, setGoal] = useState(draft.taskContract?.goal ?? "");
  const [audience, setAudience] = useState(draft.taskContract?.audience ?? "当前用户");
  const [inputs, setInputs] = useState(draft.taskContract?.inputs.join("\n") ?? "用户请求");
  const [outputs, setOutputs] = useState(draft.taskContract?.outputs.join("\n") ?? "可验证的最终结果");
  const [constraints, setConstraints] = useState(draft.taskContract?.constraints.join("\n") ?? "不得绕过权限、审批和证据要求");
  const [examples, setExamples] = useState(draft.taskContract?.examples.join("\n") ?? "");
  const [result, setResult] = useState<StudioAgentBuilderPatch | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  if (!open) return null;

  async function generate() {
    setBusy(true); setError(""); setResult(null);
    try {
      setResult(await studioClient.createAgentBuilderPatch(draft.id, {
        expectedRevision: draft.revision,
        goal, audience, inputs: lines(inputs), outputs: lines(outputs),
        constraints: lines(constraints), examples: lines(examples),
      }));
    } catch (reason) { setError(reason instanceof Error ? reason.message : "生成失败"); }
    finally { setBusy(false); }
  }

  function apply() {
    if (!result || result.baseRevision !== draft.revision) return;
    const cases: StudioEvalCase[] = result.evaluationCases.map((item) => ({
      id: item.id,
      label: item.id === "builder-happy-path" ? "正常路径" : item.id === "builder-ambiguous-input" ? "输入歧义" : "安全边界",
      tag: (item.tags.find((tag) => ["happy", "ambiguous", "safety"].includes(tag)) ?? "happy") as StudioEvalCase["tag"],
      prompt: item.prompt,
      expect: item.expect,
    }));
    onApply({ taskContract: result.taskContract, systemPrompt: result.systemPrompt, evalCases: cases, evaluationEnabled: true });
    onClose();
  }

  return <div className={styles.backdrop}><section className={`${styles.dialog} ${styles.large}`} role="dialog" aria-modal="true"><header><div><span>AGENT COPILOT</span><h2>从 TaskContract 构建 Agent</h2></div><button type="button" onClick={onClose}>×</button></header>
    <p>先生成结构化 Patch；审阅后才应用到当前草稿。</p>
    <div className={styles.copilotColumns}><div className={styles.formGrid}>
      <label className={styles.wide}><span>目标</span><textarea value={goal} onChange={(e) => setGoal(e.target.value)} /></label>
      <label><span>受众</span><input value={audience} onChange={(e) => setAudience(e.target.value)} /></label>
      <label><span>输入（每行一项）</span><textarea value={inputs} onChange={(e) => setInputs(e.target.value)} /></label>
      <label><span>输出（每行一项）</span><textarea value={outputs} onChange={(e) => setOutputs(e.target.value)} /></label>
      <label><span>边界（每行一项）</span><textarea value={constraints} onChange={(e) => setConstraints(e.target.value)} /></label>
      <label className={styles.wide}><span>示例（可选）</span><textarea value={examples} onChange={(e) => setExamples(e.target.value)} /></label>
    </div><div className={styles.review}>
      {!result && <div className={styles.empty}>生成后在这里审阅 TaskContract、Prompt 与三类评测。</div>}
      {result && <><div className={styles.readiness} data-ready={result.validation.ready}>{result.validation.ready ? "编译检查通过" : `${result.validation.issues.length} 项需处理`}</div><h3>结构化变更</h3><ul>{result.explanation.map((item) => <li key={item}>{item}</li>)}</ul><h3>System Prompt</h3><pre>{result.systemPrompt}</pre><h3>基础评测</h3>{result.evaluationCases.map((item) => <div className={styles.evalCard} key={item.id}><strong>{item.id}</strong><small>{item.prompt}</small></div>)}</>}
    </div></div>
    {error && <p className={styles.error}>{error}</p>}
    <footer><button type="button" onClick={onClose}>取消</button><button type="button" disabled={busy || !goal.trim() || lines(inputs).length === 0 || lines(outputs).length === 0} onClick={() => void generate()}>{busy ? "生成中…" : "生成 Patch"}</button><button type="button" className={styles.primary} disabled={!result || result.baseRevision !== draft.revision} onClick={apply}>审阅并应用</button></footer>
  </section></div>;
}

export function TryRunPanel({
  open,
  draft,
  initialPrompt,
  autoStart,
  recommendation,
  canSolidify,
  onClose,
  onSolidified,
}: {
  open: boolean;
  draft: StudioDraft;
  initialPrompt: string;
  autoStart: boolean;
  recommendation: StudioTaskDrivenRecommendation | null;
  canSolidify: boolean;
  onClose: () => void;
  onSolidified: (result: StudioSolidifiedAgentResult) => void;
}) {
  const [prompt, setPrompt] = useState(initialPrompt);
  const [result, setResult] = useState<StudioTryRun | null>(null);
  const [solidified, setSolidified] = useState<StudioSolidifiedAgentResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [solidifying, setSolidifying] = useState(false);
  const [error, setError] = useState("");
  const autoRunRef = useRef("");
  const terminal = useMemo(
    () => result ? ["cancelled", "succeeded", "failed", "timed_out", "rejected"].includes(result.run.status) : false,
    [result],
  );

  useEffect(() => {
    if (!open) return;
    setPrompt(initialPrompt);
    setResult(null);
    setSolidified(null);
    setError("");
    const key = `${draft.id}:${initialPrompt}`;
    if (autoStart && initialPrompt.trim() && autoRunRef.current !== key) {
      autoRunRef.current = key;
      void startRun(initialPrompt);
    }
  // A newly created flow owns this reset; draft publication updates must not restart it.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, draft.id, initialPrompt, autoStart]);

  useEffect(() => {
    if (!open || !result || terminal) return;
    const timer = window.setInterval(() => {
      void studioClient
        .getTryRun(draft.id, result.draftRevision, result.run.run_id)
        .then(setResult)
        .catch((reason) => setError(reason instanceof Error ? reason.message : "刷新失败"));
    }, 1200);
    return () => window.clearInterval(timer);
  }, [open, result, terminal, draft.id]);
  if (!open) return null;

  async function startRun(value: string) {
    setBusy(true);
    setError("");
    setResult(null);
    setSolidified(null);
    try {
      setResult(await studioClient.createTryRun(
        draft.id,
        draft.revision,
        value,
        `studio-try-${createRandomId()}`,
      ));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "试跑失败");
    } finally {
      setBusy(false);
    }
  }

  async function decide(id: string, decision: "approved" | "rejected") {
    await studioClient.decideTryRunApproval(id, decision);
    if (result) {
      setResult(await studioClient.getTryRun(
        draft.id,
        result.draftRevision,
        result.run.run_id,
      ));
    }
  }

  async function solidify() {
    if (!result || result.run.status !== "succeeded" || solidifying) return;
    setSolidifying(true);
    setError("");
    try {
      const next = await studioClient.solidifyTryRun(
        draft.id,
        result.draftRevision,
        result.draftRevision,
        result.run.run_id,
      );
      setSolidified(next);
      onSolidified(next);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "固化失败");
    } finally {
      setSolidifying(false);
    }
  }

  const traces = result?.events.filter((item) => [
    "tool.request",
    "tool.result",
    "tool.allowed",
    "tool.denied",
  ].includes(item.type)) ?? [];
  const statusLabel = result?.run.status === "succeeded"
    ? "试跑成功"
    : result?.run.status === "failed"
      ? "试跑失败"
      : result?.run.status ?? "未运行";

  return <aside className={styles.tryPanel} aria-label="Codex Loop 试跑">
    <header><div><span>CODEX LOOP</span><h2>从任务到可固化 Agent</h2></div><button type="button" onClick={onClose}>×</button></header>
    <p><code>{draft.name}@r{result?.draftRevision ?? draft.revision}</code> · 计划、工具、修正、验证都来自真实运行事件；不会展示模型隐藏推理。</p>
    {recommendation && <section className={styles.recommendationStrip}>
      <div><span>BUILDER RECOMMENDATION</span><strong>{recommendation.runtime}</strong><small>{recommendation.modelRouteId} / {recommendation.model}</small></div>
      <div><strong>{recommendation.builtinTools.length} Tools</strong><small>{recommendation.builtinTools.join(" · ") || "无"}</small></div>
      <div><strong>{recommendation.mcpServers.length} MCP</strong><small>{recommendation.mcpServers.join(" · ") || "未扩大外部边界"}</small></div>
    </section>}
    <label><span>测试任务</span><textarea value={prompt} onChange={(event) => setPrompt(event.target.value)} placeholder="输入一个能验证该 Agent 的真实任务…" /></label>
    <div className={styles.runActions}>
      <button type="button" className={styles.primary} disabled={busy || !prompt.trim() || Boolean(result && !terminal)} onClick={() => void startRun(prompt)}>{busy ? "启动隔离运行…" : result && terminal ? "重新试跑" : "运行草稿"}</button>
      {result && !terminal && <button type="button" onClick={() => void studioClient.cancelTryRun(result.run.run_id)}>取消</button>}
      <strong data-status={result?.run.status ?? "idle"}>{statusLabel}</strong>
    </div>
    {error && <p className={styles.error}>{error}</p>}
    {result && <div className={styles.runResult}>
      <section className={styles.loopSection}>
        <div className={styles.sectionTitle}><div><span>OBSERVABLE EXECUTION</span><h3>Codex Loop</h3></div><small>{result.run.run_id.slice(0, 12)}</small></div>
        <ol className={styles.loopRail}>{result.loop.map((stage, index) => <li key={stage.id} data-status={stage.status}>
          <div className={styles.loopMarker}><span>{index + 1}</span></div>
          <div className={styles.loopContent}><div><strong>{stage.label}</strong><em>{stage.status}</em></div><p>{stage.summary}</p>{stage.evidence.length > 0 && <details><summary>{stage.evidence.length} 条运行证据</summary><ul>{stage.evidence.map((item) => <li key={`${stage.id}-${item.sequence}-${item.eventType}`}><code>{item.sequence}</code><span>{item.summary}</span></li>)}</ul></details>}</div>
        </li>)}</ol>
      </section>
      <section className={styles.finalResult}><h3>结果</h3><pre>{result.finalText || "等待模型输出…"}</pre>
        {result.run.status === "succeeded" && !solidified && <div className={styles.solidifyCallout}><div><strong>本次试跑已通过验证</strong><p>固化后得到不可覆盖的 <code>{draft.name}@{draft.version}</code>、Agent Bundle 和 required Eval Dataset。</p></div><button type="button" className={styles.primary} disabled={!canSolidify || solidifying} onClick={() => void solidify()}>{solidifying ? "正在固化…" : canSolidify ? `固化为 ${draft.name}@${draft.version}` : "需要 Owner / Admin 固化"}</button></div>}
        {solidified && <div className={styles.solidified}><span>IMMUTABLE AGENT</span><strong>{solidified.version.name}@{solidified.version.version}</strong><small>评测基线 {solidified.dataset.datasetId}@{solidified.dataset.version} · revision {solidified.dataset.sourceDraftRevision}</small></div>}
      </section>
      <details className={styles.evidenceGroup}><summary>工具与原始运行证据 <small>{traces.length}</small></summary>{traces.map((item) => <details key={item.event_id}><summary>{item.sequence} · {item.type}</summary><pre>{JSON.stringify(item.payload, null, 2)}</pre></details>)}{traces.length === 0 && <p>本次任务未触发工具。</p>}</details>
      {result.approvals.length > 0 && <section><h3>审批 <small>{result.approvals.length}</small></h3>{result.approvals.map((item) => <div className={styles.approval} key={item.approval_id}><div><strong>{item.tool_name ?? "工具审批"}</strong><small>{item.reason}</small></div><em>{item.status}</em>{item.status === "pending" && <><button type="button" onClick={() => void decide(item.approval_id, "approved")}>批准</button><button type="button" onClick={() => void decide(item.approval_id, "rejected")}>拒绝</button></>}</div>)}</section>}
      {result.artifacts.length > 0 && <section><h3>产物 <small>{result.artifacts.length}</small></h3>{result.artifacts.map((item) => <a key={item.artifact_id} href={studioClient.tryRunArtifactHref(item.artifact_id)} download={item.name}><span>{item.name}</span><small>{item.media_type} · {item.size_bytes ?? 0} bytes</small></a>)}</section>}
    </div>}
  </aside>;
}
