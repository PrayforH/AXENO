"use client";

import {
  type FormEvent,
  useCallback,
  useEffect,
  useMemo,
  useState,
} from "react";
import { useAuth } from "../auth-provider";
import {
  studioClient,
  type StudioKnowledgeBase,
  type StudioKnowledgeHit,
  type StudioKnowledgeSource,
} from "../../lib/studio-client";
import styles from "./knowledge-control-plane.module.css";

const HEALTH = {
  pending: "等待首次同步",
  healthy: "可检索",
  degraded: "同步异常",
  disabled: "已停用",
} as const;

function slug(value: string) {
  return value
    .trim()
    .toLocaleLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 80);
}

export function KnowledgeControlPlane() {
  const { membership } = useAuth();
  const canAdmin = membership.role === "owner" || membership.role === "admin";
  const [bases, setBases] = useState<StudioKnowledgeBase[]>([]);
  const [sources, setSources] = useState<StudioKnowledgeSource[]>([]);
  const [sourceMode, setSourceMode] = useState<"file" | "web">("file");
  const [selectedSources, setSelectedSources] = useState<string[]>([]);
  const [searchBase, setSearchBase] = useState("");
  const [hits, setHits] = useState<StudioKnowledgeHit[]>([]);
  const [busy, setBusy] = useState("");
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    try {
      const [nextBases, nextSources] = await Promise.all([
        studioClient.listKnowledgeBases(),
        studioClient.listKnowledgeSources(),
      ]);
      setBases(nextBases);
      setSources(nextSources);
      setSearchBase((current) => current || nextBases[0]?.reference || "");
      setError("");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "知识控制面暂时不可用");
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const sourceByReference = useMemo(
    () => new Map(sources.map((source) => [source.reference, source])),
    [sources],
  );

  async function createSource(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const formElement = event.currentTarget;
    const form = new FormData(formElement);
    const displayName = String(form.get("displayName")).trim();
    const reference = slug(String(form.get("reference")) || displayName);
    if (!reference) {
      setError("逻辑引用只能包含小写英文、数字和连字符");
      return;
    }
    setBusy("source");
    setNotice("");
    try {
      if (sourceMode === "file") {
        const title = String(form.get("title")).trim() || displayName;
        await studioClient.createKnowledgeSource({
          reference,
          displayName,
          kind: "file",
          config: {
            type: "file",
            documents: [{
              documentId: `${reference}-document`,
              title,
              content: String(form.get("content")),
              sourceUri: `knowledge://studio/${reference}`,
            }],
          },
        });
      } else {
        await studioClient.createKnowledgeSource({
          reference,
          displayName,
          kind: "web",
          config: {
            type: "web",
            url: String(form.get("url")),
            title: displayName,
            maxBytes: 2 * 1024 * 1024,
          },
        });
      }
      formElement.reset();
      setNotice("数据源已同步并生成不可变快照。");
      await load();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "数据源创建失败");
    } finally {
      setBusy("");
    }
  }

  async function createBase(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const formElement = event.currentTarget;
    const form = new FormData(formElement);
    const displayName = String(form.get("displayName")).trim();
    const reference = slug(String(form.get("reference")) || displayName);
    setBusy("base");
    try {
      await studioClient.createKnowledgeBase({
        reference,
        displayName,
        description: String(form.get("description")),
        sourceReferences: selectedSources,
      });
      setSelectedSources([]);
      formElement.reset();
      setNotice("知识库已创建，可以在 Agent 的能力页绑定。");
      await load();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "知识库创建失败");
    } finally {
      setBusy("");
    }
  }

  async function sync(reference: string) {
    setBusy(`sync:${reference}`);
    try {
      const result = await studioClient.syncKnowledgeSource(reference);
      setNotice(
        result.status === "unchanged"
          ? "内容未变化，继续使用现有快照。"
          : `同步完成 · ${result.documentsSeen} 文档 / ${result.chunksWritten} 片段`,
      );
      await load();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "同步失败");
    } finally {
      setBusy("");
    }
  }

  async function search(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    if (!searchBase) return;
    setBusy("search");
    try {
      const result = await studioClient.searchKnowledge(
        String(form.get("query")),
        [searchBase],
      );
      setHits(result.hits);
      setNotice(`检索完成 · ${result.hits.length} 条带引用结果`);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "检索失败");
    } finally {
      setBusy("");
    }
  }

  return (
    <section className={styles.knowledge} aria-labelledby="knowledge-heading">
      <header className={styles.heading}>
        <div>
          <p>Governed knowledge</p>
          <h2 id="knowledge-heading">知识库与数据源</h2>
          <span>权限先于检索；每次有效同步生成不可变快照，并为回答保留可检查引用。</span>
        </div>
        <div className={styles.metrics}>
          <span><strong>{bases.length}</strong>知识库</span>
          <span><strong>{sources.filter((item) => item.health === "healthy").length}</strong>健康源</span>
        </div>
      </header>

      {notice && <p className={styles.notice} role="status">{notice}</p>}
      {error && <p className={styles.error} role="alert">{error}<button type="button" onClick={() => setError("")}>关闭</button></p>}

      <div className={styles.inventory}>
        <div className={styles.bases}>
          <header><div><strong>知识库</strong><span>Agent 绑定的稳定逻辑引用</span></div></header>
          {bases.length ? bases.map((base) => (
            <article key={base.reference}>
              <div>
                <strong>{base.displayName}</strong>
                <code>{base.reference}</code>
                <span>{base.description || "组织知识"}</span>
              </div>
              <small>
                {base.sourceReferences.map((reference) =>
                  sourceByReference.get(reference)?.displayName ?? reference
                ).join(" · ") || "尚未绑定数据源"}
              </small>
            </article>
          )) : <p className={styles.empty}>创建数据源后，把一个或多个来源组合成知识库。</p>}
        </div>

        <div className={styles.sources}>
          <header><div><strong>数据源</strong><span>连接器健康与活动快照</span></div><button type="button" onClick={() => void load()}>刷新</button></header>
          {sources.length ? sources.map((source) => (
            <article key={source.reference} data-health={source.health}>
              <i aria-hidden="true" />
              <div>
                <strong>{source.displayName}</strong>
                <span>{source.kind === "web" ? "Web · 不可信内容" : "文件 · 敏感内容"}</span>
                <code>{source.activeSnapshotId ?? "等待快照"}</code>
              </div>
              <small>{HEALTH[source.health]}{source.lastSyncAt ? ` · ${new Date(source.lastSyncAt).toLocaleString("zh-CN")}` : ""}</small>
              {canAdmin && source.health !== "disabled" && (
                <button
                  type="button"
                  disabled={busy === `sync:${source.reference}`}
                  onClick={() => void sync(source.reference)}
                >
                  {busy === `sync:${source.reference}` ? "同步中" : "同步"}
                </button>
              )}
            </article>
          )) : <p className={styles.empty}>当前没有文件或 Web 数据源。</p>}
        </div>
      </div>

      {canAdmin && (
        <div className={styles.authoring}>
          <details>
            <summary>添加数据源 <small>文件 / Web</small></summary>
            <form onSubmit={createSource}>
              <div className={styles.mode} role="group" aria-label="数据源类型">
                <button type="button" data-active={sourceMode === "file"} onClick={() => setSourceMode("file")}>文件内容</button>
                <button type="button" data-active={sourceMode === "web"} onClick={() => setSourceMode("web")}>HTTPS 页面</button>
              </div>
              <label><span>名称</span><input name="displayName" required placeholder="员工手册" /></label>
              <label><span>逻辑引用</span><input name="reference" placeholder="employee-handbook" /></label>
              {sourceMode === "file" ? (
                <>
                  <label><span>文档标题</span><input name="title" placeholder="休假制度" /></label>
                  <label className={styles.wide}><span>正文</span><textarea name="content" required rows={7} placeholder="粘贴 Markdown 或纯文本；同步后会切片并生成引用。" /></label>
                </>
              ) : (
                <label className={styles.wide}><span>HTTPS URL</span><input name="url" type="url" pattern="https://.*" required placeholder="https://docs.example.com/policy" /></label>
              )}
              <footer><span>Web 连接器拒绝私网、非 HTTPS、非常规端口和超限响应。</span><button disabled={busy === "source"}>{busy === "source" ? "正在同步…" : "创建并同步"}</button></footer>
            </form>
          </details>

          <details>
            <summary>创建知识库 <small>组合数据源</small></summary>
            <form onSubmit={createBase}>
              <label><span>名称</span><input name="displayName" required placeholder="公司制度" /></label>
              <label><span>逻辑引用</span><input name="reference" placeholder="company-policy" /></label>
              <label className={styles.wide}><span>说明</span><input name="description" placeholder="供内部问答和报告引用的已审核制度。" /></label>
              <fieldset className={styles.wide}>
                <legend>选择数据源</legend>
                {sources.map((source) => (
                  <label key={source.reference}>
                    <input
                      type="checkbox"
                      checked={selectedSources.includes(source.reference)}
                      onChange={() => setSelectedSources((current) =>
                        current.includes(source.reference)
                          ? current.filter((item) => item !== source.reference)
                          : [...current, source.reference]
                      )}
                    />
                    <span>{source.displayName}<small>{HEALTH[source.health]}</small></span>
                  </label>
                ))}
              </fieldset>
              <footer><span>知识库引用会进入 Agent Manifest 和环境允许列表。</span><button disabled={busy === "base" || !selectedSources.length}>{busy === "base" ? "正在创建…" : "创建知识库"}</button></footer>
            </form>
          </details>
        </div>
      )}

      <div className={styles.preview}>
        <header><div><strong>权限内检索预览</strong><span>使用当前登录身份，结果不会绕过数据源 ACL。</span></div></header>
        <form onSubmit={search}>
          <select value={searchBase} onChange={(event) => setSearchBase(event.target.value)} aria-label="知识库">
            {bases.map((base) => <option key={base.reference} value={base.reference}>{base.displayName}</option>)}
          </select>
          <input name="query" required disabled={!bases.length} placeholder="输入一个需要引用资料回答的问题" />
          <button disabled={!bases.length || busy === "search"}>{busy === "search" ? "检索中…" : "检索"}</button>
        </form>
        {hits.length > 0 && <div className={styles.hits}>{hits.map((hit) => (
          <article key={hit.citation.chunkId}>
            <header><strong>{hit.citation.title}</strong><span data-trust={hit.trust}>{hit.trust === "untrusted" ? "不可信" : "敏感"}</span><small>{Math.round(hit.score * 100)}%</small></header>
            <p>{hit.content}</p>
            <footer>
              <a
                href={
                  /^https?:\/\//.test(hit.citation.uri)
                    ? hit.citation.uri
                    : `/api/studio/knowledge/citations/${encodeURIComponent(hit.citation.snapshotId)}/${encodeURIComponent(hit.citation.chunkId)}`
                }
                target="_blank"
                rel="noreferrer"
              >
                打开来源 · {hit.citation.uri}
              </a>
              <code>{hit.citation.snapshotId.slice(-12)} / {hit.citation.chunkId.slice(0, 10)}</code>
            </footer>
          </article>
        ))}</div>}
      </div>
    </section>
  );
}
