"use client";

import { type FormEvent, useCallback, useEffect, useMemo, useState } from "react";
import { StudioSidebar } from "../agent-studio/studio-sidebar";
import styles from "./team-spaces.module.css";

type SpaceRole = "owner" | "admin" | "contributor" | "viewer";
type TeamSpace = {
  tenantId: string;
  spaceId: string;
  name: string;
  description: string;
  createdBy: string;
  createdAt: string;
};
type SpaceMember = {
  tenantId: string;
  spaceId: string;
  userId: string;
  role: SpaceRole;
  createdAt: string;
};
type SpaceSummary = { space: TeamSpace; membership: SpaceMember };
type TenantMember = {
  user: { user_id: string; display_name: string; email: string };
  membership: { role: string };
};
type CatalogAgent = {
  name: string;
  version: string;
  display_name: string;
  domain: string;
  owner_user_id: string;
  scope: "personal" | "team";
};
type SharedAgent = {
  grant: {
    spaceId: string;
    agentOwnerUserId: string;
    agentName: string;
    agentVersion: string;
    sharedBy: string;
    runnableByViewer: boolean;
  };
  agent: CatalogAgent;
};
type KnowledgeBase = { reference: string; displayName: string; description: string };
type SharedKnowledge = {
  spaceId: string;
  knowledgeBaseReference: string;
  sharedBy: string;
  createdAt: string;
};

const ROLE_LABELS: Record<SpaceRole, string> = {
  owner: "所有者",
  admin: "管理员",
  contributor: "贡献者",
  viewer: "查看者",
};

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, { cache: "no-store", ...init });
  if (!response.ok) {
    const payload = (await response.json().catch(() => null)) as
      | { error?: { message?: string } }
      | null;
    throw new Error(payload?.error?.message || `HTTP ${response.status}`);
  }
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

function agentKey(agent: Pick<CatalogAgent, "owner_user_id" | "name" | "version">) {
  return `${agent.owner_user_id}:${agent.name}@${agent.version}`;
}

export function TeamSpaces() {
  const [spaces, setSpaces] = useState<SpaceSummary[]>([]);
  const [selectedId, setSelectedId] = useState("");
  const [members, setMembers] = useState<SpaceMember[]>([]);
  const [directory, setDirectory] = useState<TenantMember[]>([]);
  const [personalAgents, setPersonalAgents] = useState<CatalogAgent[]>([]);
  const [sharedAgents, setSharedAgents] = useState<SharedAgent[]>([]);
  const [knowledgeBases, setKnowledgeBases] = useState<KnowledgeBase[]>([]);
  const [sharedKnowledge, setSharedKnowledge] = useState<SharedKnowledge[]>([]);
  const [spaceName, setSpaceName] = useState("");
  const [spaceDescription, setSpaceDescription] = useState("");
  const [memberUserId, setMemberUserId] = useState("");
  const [memberRole, setMemberRole] = useState<SpaceRole>("contributor");
  const [agentSelection, setAgentSelection] = useState("");
  const [viewerRunnable, setViewerRunnable] = useState(true);
  const [knowledgeSelection, setKnowledgeSelection] = useState("");
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  const selected = spaces.find((item) => item.space.spaceId === selectedId) ?? null;
  const canManage = selected?.membership.role === "owner" || selected?.membership.role === "admin";
  const canShare = canManage || selected?.membership.role === "contributor";
  const memberById = useMemo(
    () => new Map(directory.map((item) => [item.user.user_id, item])),
    [directory],
  );

  const loadSpaces = useCallback(async () => {
    const values = await request<SpaceSummary[]>("/api/spaces");
    setSpaces(values);
    setSelectedId((current) =>
      values.some((item) => item.space.spaceId === current)
        ? current
        : values[0]?.space.spaceId ?? "",
    );
  }, []);

  const loadSpace = useCallback(async (spaceId: string) => {
    if (!spaceId) {
      setMembers([]);
      setDirectory([]);
      setSharedAgents([]);
      setSharedKnowledge([]);
      return;
    }
    const summary = spaces.find((item) => item.space.spaceId === spaceId);
    const manageable = summary?.membership.role === "owner" || summary?.membership.role === "admin";
    const [nextMembers, nextShared, nextKnowledge, nextDirectory] = await Promise.all([
      request<SpaceMember[]>(`/api/spaces/${encodeURIComponent(spaceId)}/members`),
      request<SharedAgent[]>(`/api/spaces/${encodeURIComponent(spaceId)}/agents`),
      request<SharedKnowledge[]>(`/api/spaces/${encodeURIComponent(spaceId)}/knowledge`),
      manageable
        ? request<TenantMember[]>(`/api/spaces/${encodeURIComponent(spaceId)}/member-directory`)
        : Promise.resolve([]),
    ]);
    setMembers(nextMembers);
    setSharedAgents(nextShared);
    setSharedKnowledge(nextKnowledge);
    setDirectory(nextDirectory);
    setMemberUserId((current) =>
      nextDirectory.some((item) => item.user.user_id === current)
        ? current
        : nextDirectory[0]?.user.user_id ?? "",
    );
  }, [spaces]);

  useEffect(() => {
    Promise.all([
      loadSpaces(),
      request<CatalogAgent[]>("/api/harness/agents").then((items) => {
        const personal = items.filter((item) => item.scope === "personal");
        setPersonalAgents(personal);
        setAgentSelection(personal[0] ? agentKey(personal[0]) : "");
      }),
      request<KnowledgeBase[]>("/api/studio/knowledge/bases").then((items) => {
        setKnowledgeBases(items);
        setKnowledgeSelection(items[0]?.reference ?? "");
      }).catch(() => undefined),
    ]).catch((caught) => setError(caught instanceof Error ? caught.message : "共享空间暂不可用"));
  }, [loadSpaces]);

  useEffect(() => {
    void loadSpace(selectedId).catch((caught) =>
      setError(caught instanceof Error ? caught.message : "空间内容暂不可用"),
    );
  }, [loadSpace, selectedId]);

  async function createSpace(event: FormEvent) {
    event.preventDefault();
    setBusy("create"); setError(""); setNotice("");
    try {
      const created = await request<SpaceSummary>("/api/spaces", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: spaceName, description: spaceDescription }),
      });
      setSpaceName(""); setSpaceDescription("");
      await loadSpaces();
      setSelectedId(created.space.spaceId);
      setNotice(`已创建团队空间「${created.space.name}」。`);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "创建失败");
    } finally { setBusy(""); }
  }

  async function addMember(event: FormEvent) {
    event.preventDefault();
    if (!selectedId || !memberUserId) return;
    setBusy("member"); setError(""); setNotice("");
    try {
      await request(`/api/spaces/${encodeURIComponent(selectedId)}/members`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ user_id: memberUserId, role: memberRole }),
      });
      await loadSpace(selectedId);
      setNotice("空间成员权限已保存；其私人任务仍不可见。");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "成员保存失败");
    } finally { setBusy(""); }
  }

  async function shareAgent(event: FormEvent) {
    event.preventDefault();
    const agent = personalAgents.find((item) => agentKey(item) === agentSelection);
    if (!selectedId || !agent) return;
    setBusy("share"); setError(""); setNotice("");
    try {
      await request(`/api/spaces/${encodeURIComponent(selectedId)}/agents`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          owner_user_id: agent.owner_user_id,
          name: agent.name,
          version: agent.version,
          runnable_by_viewer: viewerRunnable,
        }),
      });
      await loadSpace(selectedId);
      setNotice(`${agent.display_name} ${agent.version} 已发布到团队空间。`);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "发布失败");
    } finally { setBusy(""); }
  }

  async function forkAgent(item: SharedAgent) {
    const grant = item.grant;
    setBusy(`fork:${grant.agentName}`); setError(""); setNotice("");
    try {
      await request(
        `/api/spaces/${encodeURIComponent(selectedId)}/agents/${encodeURIComponent(grant.agentOwnerUserId)}/${encodeURIComponent(grant.agentName)}/${encodeURIComponent(grant.agentVersion)}/fork`,
        { method: "POST" },
      );
      const agents = await request<CatalogAgent[]>("/api/harness/agents");
      setPersonalAgents(agents.filter((agent) => agent.scope === "personal"));
      setNotice("已复制到个人智能体；团队版本及其他成员任务未发生变化。");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "复制失败");
    } finally { setBusy(""); }
  }

  async function unshareAgent(item: SharedAgent) {
    const grant = item.grant;
    setBusy(`remove:${grant.agentName}`); setError(""); setNotice("");
    try {
      await request(
        `/api/spaces/${encodeURIComponent(selectedId)}/agents/${encodeURIComponent(grant.agentOwnerUserId)}/${encodeURIComponent(grant.agentName)}/${encodeURIComponent(grant.agentVersion)}`,
        { method: "DELETE" },
      );
      await loadSpace(selectedId);
      setNotice("共享授权已撤销；既有任务仍保留其历史快照和记录。");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "撤销失败");
    } finally { setBusy(""); }
  }

  async function shareKnowledge(event: FormEvent) {
    event.preventDefault();
    if (!selectedId || !knowledgeSelection) return;
    setBusy("knowledge"); setError(""); setNotice("");
    try {
      await request(`/api/spaces/${encodeURIComponent(selectedId)}/knowledge`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ reference: knowledgeSelection }),
      });
      await loadSpace(selectedId);
      setNotice("知识库授权已发布到团队空间；检索仍只发生在成员自己的任务中。");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "知识库共享失败");
    } finally { setBusy(""); }
  }

  async function unshareKnowledge(reference: string) {
    setBusy(`knowledge:${reference}`); setError(""); setNotice("");
    try {
      await request(
        `/api/spaces/${encodeURIComponent(selectedId)}/knowledge/${encodeURIComponent(reference)}`,
        { method: "DELETE" },
      );
      await loadSpace(selectedId);
      setNotice("知识库空间授权已撤销；历史任务不会被转移或公开。");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "撤销失败");
    } finally { setBusy(""); }
  }

  return (
    <main className={styles.shell} id="main-content">
      <StudioSidebar active="spaces">
        <div className={styles.railCopy}>
          <strong>个人与团队边界</strong>
          <p>共享不可变 Agent 版本；任务、对话、文件和 MCP 凭据始终属于运行用户。</p>
        </div>
      </StudioSidebar>
      <section className={styles.content}>
        <header className={styles.hero}>
          <div><p>Team collaboration</p><h1>共享空间</h1><span>把可复用能力发布给团队，而不是共享个人运行记录。</span></div>
          <form onSubmit={createSpace} className={styles.createForm}>
            <input value={spaceName} onChange={(event) => setSpaceName(event.target.value)} placeholder="空间名称" maxLength={160} required />
            <input value={spaceDescription} onChange={(event) => setSpaceDescription(event.target.value)} placeholder="用途说明（可选）" maxLength={1000} />
            <button disabled={busy === "create"}>{busy === "create" ? "创建中" : "新建空间"}</button>
          </form>
        </header>

        {(notice || error) && <p className={error ? styles.error : styles.notice} role={error ? "alert" : "status"}>{error || notice}</p>}

        <div className={styles.workspace}>
          <nav className={styles.spaceList} aria-label="团队空间">
            {spaces.length === 0 ? <p>还没有团队空间。</p> : spaces.map((item) => (
              <button key={item.space.spaceId} data-active={item.space.spaceId === selectedId || undefined} onClick={() => setSelectedId(item.space.spaceId)}>
                <strong>{item.space.name}</strong><span>{ROLE_LABELS[item.membership.role]}</span><small>{item.space.description || "未填写说明"}</small>
              </button>
            ))}
          </nav>

          {selected ? <div className={styles.detail}>
            <section className={styles.summary}>
              <div><p>当前空间</p><h2>{selected.space.name}</h2><span>{selected.space.description || "用于团队共享可运行的 Agent 版本。"}</span></div>
              <div className={styles.boundaries}><span><b>{members.length}</b> 成员</span><span><b>{sharedAgents.length}</b> Agent</span><span><b>{sharedKnowledge.length}</b> 知识库</span><span><b>0</b> 共享任务</span></div>
            </section>

            <section className={styles.panel}>
              <header><div><p>Members & RBAC</p><h3>空间成员</h3></div><span>Owner › Admin › Contributor › Viewer</span></header>
              {canManage && <form className={styles.inlineForm} onSubmit={addMember}>
                <select value={memberUserId} onChange={(event) => setMemberUserId(event.target.value)}>
                  {directory.map((item) => <option value={item.user.user_id} key={item.user.user_id}>{item.user.display_name} · {item.user.email}</option>)}
                </select>
                <select value={memberRole} onChange={(event) => setMemberRole(event.target.value as SpaceRole)}>
                  <option value="contributor">贡献者</option><option value="viewer">查看者</option><option value="admin">管理员</option><option value="owner">所有者</option>
                </select>
                <button disabled={!memberUserId || busy === "member"}>保存成员</button>
              </form>}
              <div className={styles.memberGrid}>{members.map((member) => {
                const profile = memberById.get(member.userId)?.user;
                return <article key={member.userId}><span>{(profile?.display_name || member.userId).slice(0, 1).toUpperCase()}</span><div><strong>{profile?.display_name || member.userId}</strong><small>{profile?.email || "租户成员"}</small></div><em>{ROLE_LABELS[member.role]}</em></article>;
              })}</div>
            </section>

            <section className={styles.panel}>
              <header><div><p>Immutable releases</p><h3>共享智能体版本</h3></div><span>共享定义，不共享凭据和任务</span></header>
              {canShare && <form className={styles.shareForm} onSubmit={shareAgent}>
                <select value={agentSelection} onChange={(event) => setAgentSelection(event.target.value)}>
                  {personalAgents.map((agent) => <option key={agentKey(agent)} value={agentKey(agent)}>{agent.display_name} · {agent.version}</option>)}
                </select>
                <label><input type="checkbox" checked={viewerRunnable} onChange={(event) => setViewerRunnable(event.target.checked)} />允许 Viewer 运行</label>
                <button disabled={!agentSelection || busy === "share"}>发布到空间</button>
              </form>}
              <div className={styles.agentList}>{sharedAgents.length === 0 ? <p>尚未发布共享版本。</p> : sharedAgents.map((item) => <article key={`${item.grant.agentOwnerUserId}:${item.grant.agentName}@${item.grant.agentVersion}`}>
                <div><strong>{item.agent.display_name}</strong><span>{item.grant.agentName}@{item.grant.agentVersion}</span></div>
                <small>{item.grant.runnableByViewer ? "所有成员可运行" : "Viewer 仅查看"}</small>
                <div className={styles.actions}><button onClick={() => void forkAgent(item)} disabled={busy.startsWith("fork:")}>复制到个人</button>{canShare && <button className={styles.danger} onClick={() => void unshareAgent(item)} disabled={busy.startsWith("remove:")}>撤销共享</button>}</div>
              </article>)}</div>
            </section>

            <section className={styles.panel}>
              <header><div><p>Knowledge grants</p><h3>共享知识库授权</h3></div><span>空间授权可撤销，检索记录仍归运行用户</span></header>
              {canManage && <form className={styles.shareForm} onSubmit={shareKnowledge}>
                <select value={knowledgeSelection} onChange={(event) => setKnowledgeSelection(event.target.value)}>
                  {knowledgeBases.map((base) => <option key={base.reference} value={base.reference}>{base.displayName} · {base.reference}</option>)}
                </select>
                <span />
                <button disabled={!knowledgeSelection || busy === "knowledge"}>授权给空间</button>
              </form>}
              <div className={styles.agentList}>{sharedKnowledge.length === 0 ? <p>尚未共享知识库。</p> : sharedKnowledge.map((item) => {
                const base = knowledgeBases.find((candidate) => candidate.reference === item.knowledgeBaseReference);
                return <article key={item.knowledgeBaseReference}>
                  <div><strong>{base?.displayName ?? item.knowledgeBaseReference}</strong><span>{item.knowledgeBaseReference}</span></div>
                  <small>成员运行共享 Agent 时可检索</small>
                  <div className={styles.actions}>{canManage && <button className={styles.danger} onClick={() => void unshareKnowledge(item.knowledgeBaseReference)} disabled={busy.startsWith("knowledge:")}>撤销授权</button>}</div>
                </article>;
              })}</div>
            </section>
          </div> : <div className={styles.empty}><strong>创建第一个团队空间</strong><span>之后可以添加成员并发布个人 Agent 的不可变版本。</span></div>}
        </div>
      </section>
    </main>
  );
}
