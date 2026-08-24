"use client";

import { useEffect, useMemo, useState } from "react";
import {
  apiDraftToStudioDraft,
  studioClient,
  type StudioAgentBuilderPatch,
  type StudioCapabilities,
  type StudioTryRun,
} from "../../lib/studio-client";
import { createRandomId } from "../../lib/random-id";
import type { StudioDraft, StudioEvalCase } from "../../lib/agent-studio";
import styles from "./agent-builder-overlays.module.css";

function lines(value: string) {
  return value.split("\n").map((item) => item.trim()).filter(Boolean);
}

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
  onCreated: (draft: StudioDraft) => void;
}) {
  const [template, setTemplate] = useState<StudioDraft["template"]>("analyst");
  const [displayName, setDisplayName] = useState("");
  const [name, setName] = useState("");
  const [domain, setDomain] = useState("general");
  const [description, setDescription] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  if (!open) return null;

  async function create() {
    if (!displayName.trim() || !name.trim() || !description.trim()) return;
    if (reservedNames.includes(name.trim())) {
      setError("该 Agent 名称已存在");
      return;
    }
    setBusy(true);
    setError("");
    try {
      const created = await studioClient.createDraft({
        template,
        displayName: displayName.trim(),
        name: name.trim(),
        domain: domain.trim(),
        description: description.trim(),
      });
      onCreated(apiDraftToStudioDraft(created));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "创建失败");
    } finally {
      setBusy(false);
    }
  }

  return <div className={styles.backdrop} role="presentation">
    <section className={styles.dialog} role="dialog" aria-modal="true" aria-labelledby="new-agent-title">
      <header><div><span>SERVER TEMPLATE</span><h2 id="new-agent-title">新建智能体</h2></div><button type="button" onClick={onClose}>×</button></header>
      <p>模板由服务端生成完整脚手架，创建后可继续细化。</p>
      <div className={styles.templateGrid}>
        {templates.map((item) => <button key={item.template} type="button" data-active={template === item.template} onClick={() => setTemplate(item.template)}><strong>{item.label}</strong><small>{item.description}</small></button>)}
      </div>
      <div className={styles.formGrid}>
        <label><span>显示名称</span><input value={displayName} onChange={(e) => { setDisplayName(e.target.value); if (!name) setName(e.target.value.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "")); }} /></label>
        <label><span>Agent name</span><input value={name} pattern="[a-z][a-z0-9-]*" onChange={(e) => setName(e.target.value)} /></label>
        <label><span>领域</span><input value={domain} pattern="[a-z][a-z0-9-]*" onChange={(e) => setDomain(e.target.value)} /></label>
        <label className={styles.wide}><span>用途说明</span><textarea value={description} onChange={(e) => setDescription(e.target.value)} /></label>
      </div>
      {error && <p className={styles.error}>{error}</p>}
      <footer><button type="button" onClick={onClose}>取消</button><button type="button" className={styles.primary} disabled={busy || !displayName.trim() || !name.trim() || !description.trim()} onClick={() => void create()}>{busy ? "创建中…" : "从模板创建"}</button></footer>
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

export function TryRunPanel({ open, draft, onClose }: { open: boolean; draft: StudioDraft; onClose: () => void }) {
  const [prompt, setPrompt] = useState("");
  const [result, setResult] = useState<StudioTryRun | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const terminal = useMemo(() => result ? ["cancelled", "succeeded", "failed", "timed_out", "rejected"].includes(result.run.status) : false, [result]);
  useEffect(() => {
    if (!open || !result || terminal) return;
    const timer = window.setInterval(() => {
      void studioClient.getTryRun(draft.id, result.draftRevision, result.run.run_id).then(setResult).catch((reason) => setError(reason instanceof Error ? reason.message : "刷新失败"));
    }, 1200);
    return () => window.clearInterval(timer);
  }, [open, result, terminal, draft.id]);
  if (!open) return null;

  async function run() {
    setBusy(true); setError(""); setResult(null);
    try { setResult(await studioClient.createTryRun(draft.id, draft.revision, prompt, `studio-try-${createRandomId()}`)); }
    catch (reason) { setError(reason instanceof Error ? reason.message : "试跑失败"); }
    finally { setBusy(false); }
  }
  async function decide(id: string, decision: "approved" | "rejected") {
    await studioClient.decideTryRunApproval(id, decision);
    if (result) setResult(await studioClient.getTryRun(draft.id, result.draftRevision, result.run.run_id));
  }
  const traces = result?.events.filter((item) => ["tool.request", "tool.result", "tool.allowed", "tool.denied"].includes(item.type)) ?? [];
  return <aside className={styles.tryPanel} aria-label="草稿试跑"><header><div><span>INLINE TRY RUN</span><h2>发布前试跑</h2></div><button type="button" onClick={onClose}>×</button></header><p><code>{draft.name}@r{draft.revision}</code> · 使用当前已保存草稿，不创建发布版本。</p>
    <label><span>测试任务</span><textarea value={prompt} onChange={(e) => setPrompt(e.target.value)} placeholder="输入一个能验证该 Agent 的真实任务…" /></label><div className={styles.runActions}><button type="button" className={styles.primary} disabled={busy || !prompt.trim() || Boolean(result && !terminal)} onClick={() => void run()}>{busy ? "启动中…" : "运行草稿"}</button>{result && !terminal && <button type="button" onClick={() => void studioClient.cancelTryRun(result.run.run_id)}>取消</button>}<strong>{result?.run.status ?? "未运行"}</strong></div>
    {error && <p className={styles.error}>{error}</p>}
    {result && <div className={styles.runResult}><section><h3>最终结果</h3><pre>{result.finalText || "等待模型输出…"}</pre></section><section><h3>工具轨迹 <small>{traces.length}</small></h3>{traces.map((item) => <details key={item.event_id}><summary>{item.sequence} · {item.type}</summary><pre>{JSON.stringify(item.payload, null, 2)}</pre></details>)}{traces.length === 0 && <p>尚无工具调用。</p>}</section><section><h3>审批 <small>{result.approvals.length}</small></h3>{result.approvals.map((item) => <div className={styles.approval} key={item.approval_id}><div><strong>{item.tool_name ?? "工具审批"}</strong><small>{item.reason}</small></div><em>{item.status}</em>{item.status === "pending" && <><button type="button" onClick={() => void decide(item.approval_id, "approved")}>批准</button><button type="button" onClick={() => void decide(item.approval_id, "rejected")}>拒绝</button></>}</div>)}</section><section><h3>产物 <small>{result.artifacts.length}</small></h3>{result.artifacts.map((item) => <a key={item.artifact_id} href={studioClient.tryRunArtifactHref(item.artifact_id)} download={item.name}><span>{item.name}</span><small>{item.media_type} · {item.size_bytes ?? 0} bytes</small></a>)}</section></div>}
  </aside>;
}
