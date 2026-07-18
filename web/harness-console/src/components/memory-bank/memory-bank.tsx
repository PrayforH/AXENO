"use client";

import Link from "next/link";
import { type FormEvent, useCallback, useEffect, useMemo, useState } from "react";
import { type MemoryEntry, type MemoryPolicy, memoryClient } from "../../lib/memory-client";
import { ThemeToggle } from "../theme-toggle";
import styles from "./memory-bank.module.css";

const STATUS = { pending: "待确认", active: "使用中", rejected: "已拒绝", deleted: "已删除", expired: "已过期" } as const;
const SENSITIVITY = { personal: "一般偏好", sensitive: "敏感信息", prohibited: "禁止保存" } as const;

function formatTime(value: string) {
  return new Intl.DateTimeFormat("zh-CN", { dateStyle: "medium", timeStyle: "short" }).format(new Date(value));
}

function EntryRow({ entry, busy, mutate }: { entry: MemoryEntry; busy: boolean; mutate: (action: () => Promise<unknown>, notice: string) => Promise<void> }) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(entry.content);
  const visible = entry.status !== "deleted" && entry.status !== "expired";
  async function save(event: FormEvent) {
    event.preventDefault();
    await mutate(() => memoryClient.update(entry, draft.trim()), "记忆内容已更新。");
    setEditing(false);
  }
  return <article className={styles.entry} data-status={entry.status}>
    <header className={styles.entryHead}>
      <div className={styles.entryKind}><i aria-hidden="true"/><strong>{STATUS[entry.status]}</strong><span>{SENSITIVITY[entry.sensitivity]}</span></div>
      <time dateTime={entry.updatedAt}>{formatTime(entry.updatedAt)}</time>
    </header>
    {editing ? <form className={styles.edit} onSubmit={save}><textarea aria-label="记忆内容" value={draft} maxLength={4000} required onChange={(event) => setDraft(event.target.value)}/><div className={styles.actions}><button type="button" onClick={() => setEditing(false)}>取消</button><button className={styles.primary} disabled={busy || !draft.trim()}>保存修改</button></div></form> : <>
      <p className={`${styles.content} ${visible ? "" : styles.redacted}`}>{visible ? entry.content : "内容已清除，不会再提供给智能体。"}</p>
      <div className={styles.meta}>
        <span>来源 · {entry.source.label}</span><span>智能体 · {entry.agentName}</span><span>置信度 <b className={styles.confidence}><i style={{ width: `${entry.confidence * 100}%` }}/></b>{Math.round(entry.confidence * 100)}%</span>
        {entry.expiresAt && <span>到期 · {formatTime(entry.expiresAt)}</span>}
      </div>
      {visible && <div className={styles.actions}>
        {entry.status === "pending" && <><button className={styles.danger} disabled={busy} onClick={() => void mutate(() => memoryClient.reject(entry), "已拒绝这条记忆。")} >拒绝</button><button className={styles.primary} disabled={busy} onClick={() => void mutate(() => memoryClient.confirm(entry), "记忆已确认，后续对话可以使用。")} >确认保存</button></>}
        {entry.status === "active" && <><button disabled={busy} onClick={() => setEditing(true)}>编辑</button><button className={styles.danger} disabled={busy} onClick={() => { if (window.confirm("删除后内容会立即清除，且不再提供给智能体。继续？")) void mutate(() => memoryClient.remove(entry), "记忆已删除。"); }}>删除</button></>}
      </div>}
    </>}
  </article>;
}

export function MemoryBank() {
  const [agentName, setAgentName] = useState("");
  const [entries, setEntries] = useState<MemoryEntry[]>([]);
  const [policy, setPolicy] = useState<MemoryPolicy>({ consent: null, retention: null });
  const [retention, setRetention] = useState({ defaultDays: 180, maxDays: 365 });
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const list = await memoryClient.list(agentName || undefined);
      setEntries(list);
      const selected = agentName || list[0]?.agentName || "";
      if (!agentName && selected) setAgentName(selected);
      if (selected) {
        const nextPolicy = await memoryClient.policy(selected);
        setPolicy(nextPolicy);
        setRetention({ defaultDays: nextPolicy.retention?.defaultDays ?? 180, maxDays: nextPolicy.retention?.maxDays ?? 365 });
      }
      setError(null);
    } catch (caught) { setError(caught instanceof Error ? caught.message : "长期记忆暂时不可用"); }
    finally { setLoading(false); }
  }, [agentName]);

  useEffect(() => { void load(); }, [load]);
  async function mutate(action: () => Promise<unknown>, message: string) {
    setBusy(true); setNotice(null);
    try { await action(); setNotice(message); await load(); }
    catch (caught) { setError(caught instanceof Error ? caught.message : "操作未完成"); }
    finally { setBusy(false); }
  }
  async function toggleConsent() {
    if (!agentName) return;
    const allow = !(policy.consent?.allowAgentPersonal ?? false);
    await mutate(async () => { const consent = await memoryClient.saveConsent(agentName, policy, allow); setPolicy({ ...policy, consent }); }, allow ? "已允许该智能体自动保存一般偏好。" : "已关闭自动保存，之后逐条确认。" );
  }
  async function saveRetention(event: FormEvent) {
    event.preventDefault();
    if (!agentName) return;
    await mutate(() => memoryClient.saveRetention(agentName, policy, retention.defaultDays, retention.maxDays), "保留期限已更新。");
  }
  const counts = useMemo(() => ({ active: entries.filter((item) => item.status === "active").length, pending: entries.filter((item) => item.status === "pending").length, agents: new Set(entries.map((item) => item.agentName)).size }), [entries]);

  return <main className={styles.shell} id="main-content">
    <header className={styles.topbar}><Link className={styles.brand} href="/"><span>H</span><div><strong>智能任务助手</strong><small>Agent Harness</small></div></Link><div className={styles.topbarActions}><ThemeToggle className={styles.themeToggle}/><Link className={styles.back} href="/settings">返回设置</Link></div></header>
    <div className={styles.frame}>
      <header className={styles.hero}><div><p>Managed memory ledger</p><h1>你决定智能体记住什么</h1><span>智能体只能提出记忆建议。默认逐条确认；敏感内容不会因为开启自动保存而绕过确认，密钥和提示注入内容始终拒绝保存。</span></div><div className={styles.scope}><label htmlFor="memory-agent">当前智能体</label><input id="memory-agent" value={agentName} placeholder="例如 public-opinion-agent" onChange={(event) => setAgentName(event.target.value)} onBlur={() => void load()}/><small>输入名称并移开焦点，查看该智能体的记忆与策略。</small></div></header>
      {error && <p className={styles.alert} role="alert">{error}</p>}{notice && <p className={`${styles.alert} ${styles.notice}`} role="status">{notice}</p>}
      <section className={styles.overview} aria-label="记忆概况"><div className={styles.stat}><span>正在使用</span><strong>{counts.active}</strong></div><div className={styles.stat} data-kind="pending"><span>等待确认</span><strong>{counts.pending}</strong></div><div className={styles.stat}><span>涉及智能体</span><strong>{counts.agents}</strong></div></section>
      <div className={styles.workspace}>
        <section><header className={styles.ledgerHeader}><div><p className={styles.sectionLabel}>Memory entries</p><h2>记忆记录</h2></div><div className={styles.ledgerActions}><a href="/api/memory-bank/export" download="harness-memory.json">导出 JSON</a><button type="button" disabled={loading} onClick={() => void load()}>{loading ? "正在读取…" : "刷新"}</button></div></header><div className={styles.ledger}>{entries.length ? entries.map((entry) => <EntryRow key={entry.entryId} entry={entry} busy={busy} mutate={mutate}/>) : <div className={styles.empty}><strong>{loading ? "正在读取记忆" : "还没有记忆记录"}</strong><span>{loading ? "正在核对来源与授权状态…" : "当你或智能体提出需要长期保留的信息时，会显示在这里等待确认。"}</span></div>}</div></section>
        <aside className={styles.side}><section className={styles.policy}><p className={styles.sectionLabel}>Agent policy</p><h2>保存策略</h2><span>策略只作用于 <strong>{agentName || "尚未选择的智能体"}</strong>。</span><div className={styles.toggle}><div><strong>自动保存一般偏好</strong><small>敏感信息仍需逐条确认</small></div><button type="button" role="switch" aria-label="自动保存一般偏好" aria-pressed={policy.consent?.allowAgentPersonal ?? false} disabled={busy || !agentName} onClick={() => void toggleConsent()}/></div><form onSubmit={saveRetention}><div className={styles.retention}><label>默认保留天数<input type="number" min={1} max={3650} value={retention.defaultDays} onChange={(event) => setRetention({ ...retention, defaultDays: Number(event.target.value) })}/></label><label>最长保留天数<input type="number" min={1} max={3650} value={retention.maxDays} onChange={(event) => setRetention({ ...retention, maxDays: Number(event.target.value) })}/></label></div><button className={styles.save} disabled={busy || !agentName || retention.defaultDays > retention.maxDays}>{busy ? "正在保存…" : "保存保留期限"}</button></form></section><section className={styles.principles}><strong>记忆边界</strong><ul><li>每条记录保留来源、时间和置信度</li><li>编辑使用版本校验，避免覆盖并发修改</li><li>删除立即清空正文，并停止检索召回</li><li>不同租户、用户和智能体严格隔离</li></ul></section></aside>
      </div>
    </div>
  </main>;
}
