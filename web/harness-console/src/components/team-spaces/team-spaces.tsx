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
type WorkspaceAgent = {
  tenantId: string;
  agentId: string;
  scope: "personal" | "workspace";
  ownerUserId: string | null;
  spaceId: string | null;
  name: string;
  displayName: string;
  description: string;
  status: "active" | "archived";
  currentVersion: string | null;
  createdBy: string;
  createdAt: string;
  updatedAt: string;
};
type AgentPermissions = {
  agent: WorkspaceAgent;
  permissions: string[];
  canView: boolean;
  canChat: boolean;
  canEdit: boolean;
  canPublish: boolean;
  canManage: boolean;
};
type ReleaseItem = {
  release: {
    tenantId: string;
    spaceId: string;
    agentId: string;
    version: string;
    sourceOwnerUserId: string;
    sourceName: string;
    promotedBy: string;
    runnableByViewer: boolean;
    connectionMode: "caller_owned" | "service_owned";
    createdAt: string;
  };
  agent: CatalogAgent & {
    agent_id?: string | null;
    current_version?: string | null;
    can_view?: boolean;
    can_chat?: boolean;
  };
};
type AgentAcl = {
  tenantId: string;
  agentId: string;
  granteeType: "user" | "group" | "space_role";
  granteeId: string;
  permission: string;
  grantedBy: string;
  createdAt: string;
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

const PERMISSION_LABELS: Record<string, string> = {
  view: "查看",
  chat: "对话",
  edit: "编辑",
  publish: "发布",
  manage: "管理",
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
  const [workspaceAgents, setWorkspaceAgents] = useState<AgentPermissions[]>([]);
  const [releasesByAgent, setReleasesByAgent] = useState<Record<string, ReleaseItem[]>>({});
  const [aclsByAgent, setAclsByAgent] = useState<Record<string, AgentAcl[]>>({});
  const [knowledgeBases, setKnowledgeBases] = useState<KnowledgeBase[]>([]);
  const [sharedKnowledge, setSharedKnowledge] = useState<SharedKnowledge[]>([]);
  const [spaceName, setSpaceName] = useState("");
  const [spaceDescription, setSpaceDescription] = useState("");
  const [memberUserId, setMemberUserId] = useState("");
  const [memberRole, setMemberRole] = useState<SpaceRole>("contributor");
  const [agentSelection, setAgentSelection] = useState("");
  const [viewerRunnable, setViewerRunnable] = useState(true);
  const [aclGrantee, setAclGrantee] = useState("");
  const [aclPermission, setAclPermission] = useState("chat");
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
      setWorkspaceAgents([]);
      setReleasesByAgent({});
      setAclsByAgent({});
      setSharedKnowledge([]);
      return;
    }
    const summary = spaces.find((item) => item.space.spaceId === spaceId);
    const manageable = summary?.membership.role === "owner" || summary?.membership.role === "admin";
    const [nextMembers, nextAgents, nextKnowledge, nextDirectory] = await Promise.all([
      request<SpaceMember[]>(`/api/spaces/${encodeURIComponent(spaceId)}/members`),
      request<AgentPermissions[]>(`/api/spaces/${encodeURIComponent(spaceId)}/agents`),
      request<SharedKnowledge[]>(`/api/spaces/${encodeURIComponent(spaceId)}/knowledge`),
      manageable
        ? request<TenantMember[]>(`/api/spaces/${encodeURIComponent(spaceId)}/member-directory`)
        : Promise.resolve([]),
    ]);
    setMembers(nextMembers);
    setWorkspaceAgents(nextAgents);
    setSharedKnowledge(nextKnowledge);
    setDirectory(nextDirectory);
    setMemberUserId((current) =>
      nextDirectory.some((item) => item.user.user_id === current)
        ? current
        : nextDirectory[0]?.user.user_id ?? "",
    );
    const agents = nextAgents.map((item) => item.agent);
    setAclGrantee((current) =>
      nextDirectory.some((item) => item.user.user_id === current)
        ? current
        : nextDirectory[0]?.user.user_id ?? "",
    );
    const [releases, acls] = await Promise.all([
      Promise.all(
        agents.map(async (agent) => [
          agent.agentId,
          await request<ReleaseItem[]>(
            `/api/spaces/${encodeURIComponent(spaceId)}/agents/${encodeURIComponent(agent.agentId)}/releases`,
          ),
        ] as const),
      ),
      Promise.all(
        agents.map(async (agent) => [
          agent.agentId,
          await request<AgentAcl[]>(
            `/api/spaces/${encodeURIComponent(spaceId)}/agents/${encodeURIComponent(agent.agentId)}/acl`,
          ),
        ] as const),
      ),
    ]);
    setReleasesByAgent(Object.fromEntries(releases));
    setAclsByAgent(Object.fromEntries(acls));
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
      setNotice(`${agent.display_name} ${agent.version} 已发布为工作区 Agent Release。`);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "发布失败");
    } finally { setBusy(""); }
  }

  async function promoteRelease(agentId: string, version: string) {
    if (!selectedId) return;
    setBusy(`promote:${agentId}`); setError(""); setNotice("");
    try {
      await request(
        `/api/spaces/${encodeURIComponent(selectedId)}/agents/${encodeURIComponent(agentId)}/releases/${encodeURIComponent(version)}/promote`,
        { method: "POST" },
      );
      await loadSpace(selectedId);
      setNotice(`当前发布版本已切换为 ${version}，Agent 身份不变。`);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "切换版本失败");
    } finally { setBusy(""); }
  }

  async function forkAgent(agentId: string) {
    if (!selectedId) return;
    setBusy(`fork:${agentId}`); setError(""); setNotice("");
    try {
      await request(
        `/api/spaces/${encodeURIComponent(selectedId)}/agents/${encodeURIComponent(agentId)}/fork`,
        { method: "POST" },
      );
      const agents = await request<CatalogAgent[]>("/api/harness/agents");
      setPersonalAgents(agents.filter((agent) => agent.scope === "personal"));
      setNotice("已按当前发布版本复制到个人智能体；团队 Release 未发生变化。");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "复制失败");
    } finally { setBusy(""); }
  }

  async function unshareRelease(agentId: string, version: string) {
    if (!selectedId) return;
    setBusy(`remove:${agentId}:${version}`); setError(""); setNotice("");
    try {
      await request(
        `/api/spaces/${encodeURIComponent(selectedId)}/agents/${encodeURIComponent(agentId)}/releases/${encodeURIComponent(version)}`,
        { method: "DELETE" },
      );
      await loadSpace(selectedId);
      setNotice("Release 授权已撤销；既有任务仍保留其历史快照和记录。");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "撤销失败");
    } finally { setBusy(""); }
  }

  async function addAcl(agentId: string) {
    if (!selectedId || !aclGrantee) return;
    setBusy(`acl:${agentId}`); setError(""); setNotice("");
    try {
      await request(`/api/spaces/${encodeURIComponent(selectedId)}/agents/${encodeURIComponent(agentId)}/acl`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          grantee_type: "user",
          grantee_id: aclGrantee,
          permission: aclPermission,
        }),
      });
      await loadSpace(selectedId);
      setNotice("Agent 权限已加授。");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "权限保存失败");
    } finally { setBusy(""); }
  }

  async function removeAcl(agentId: string, granteeId: string, permission: string) {
    if (!selectedId) return;
    setBusy(`acl-remove:${agentId}`); setError(""); setNotice("");
    try {
      await request(
        `/api/spaces/${encodeURIComponent(selectedId)}/agents/${encodeURIComponent(agentId)}/acl/user/${encodeURIComponent(granteeId)}/${permission}`,
        { method: "DELETE" },
      );
      await loadSpace(selectedId);
      setNotice("Agent 权限已撤销。");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "权限撤销失败");
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
          <p>工作区 Agent 拥有稳定身份；Release 切换版本不改变 Agent。</p>
        </div>
      </StudioSidebar>
      <section className={styles.content}>
        <header className={styles.hero}>
          <div><p>Team collaboration</p><h1>共享空间</h1><span>把可复用能力发布为工作区 Agent，而不是共享个人运行记录。</span></div>
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
              <div className={styles.boundaries}><span><b>{members.length}</b> 成员</span><span><b>{workspaceAgents.length}</b> Agent</span><span><b>{sharedKnowledge.length}</b> 知识库</span><span><b>0</b> 共享任务</span></div>
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
              <header><div><p>Workspace Agents</p><h3>共享智能体</h3></div><span>稳定身份 + 不可变 Release</span></header>
              {canShare && <form className={styles.shareForm} onSubmit={shareAgent}>
                <select value={agentSelection} onChange={(event) => setAgentSelection(event.target.value)}>
                  {personalAgents.map((agent) => <option key={agentKey(agent)} value={agentKey(agent)}>{agent.display_name} · {agent.version}</option>)}
                </select>
                <label><input type="checkbox" checked={viewerRunnable} onChange={(event) => setViewerRunnable(event.target.checked)} />允许 Viewer 运行</label>
                <button disabled={!agentSelection || busy === "share"}>发布 Release</button>
              </form>}
              <div className={styles.agentList}>{workspaceAgents.length === 0 ? <p>尚未发布共享 Agent。</p> : workspaceAgents.map((item) => {
                const agent = item.agent;
                const releases = releasesByAgent[agent.agentId] ?? [];
                const acls = aclsByAgent[agent.agentId] ?? [];
                return <article key={agent.agentId} className={styles.agentCard}>
                  <div><strong>{agent.displayName || agent.name}</strong><span>{agent.name} · 当前 {agent.currentVersion ?? "未发布"}</span></div>
                  <small>{item.permissions.map((permission) => PERMISSION_LABELS[permission] ?? permission).join(" / ") || "仅查看"}</small>
                  <div className={styles.releaseList}>
                    {releases.map((entry) => (
                      <div key={entry.release.version} className={`${styles.releaseRow}${entry.release.version === agent.currentVersion ? ` ${styles.releaseCurrent}` : ""}`}>
                        <span>{entry.release.version}{entry.release.version === agent.currentVersion ? " · 当前" : ""}</span>
                        <span>{entry.release.connectionMode === "service_owned" ? "共享凭据" : "个人凭据"}</span>
                        <div className={styles.actions}>
                          {item.canPublish && entry.release.version !== agent.currentVersion && <button onClick={() => void promoteRelease(agent.agentId, entry.release.version)} disabled={busy.startsWith("promote:")}>设为当前</button>}
                          {item.canPublish && <button className={styles.danger} onClick={() => void unshareRelease(agent.agentId, entry.release.version)} disabled={busy.startsWith("remove:")}>撤销</button>}
                        </div>
                      </div>
                    ))}
                  </div>
                  <div className={styles.actions}>
                    {item.canChat && <button onClick={() => void forkAgent(agent.agentId)} disabled={busy.startsWith("fork:")}>复制到个人</button>}
                  </div>
                  {item.canManage && (
                    <form className={styles.inlineForm} onSubmit={(event) => { event.preventDefault(); void addAcl(agent.agentId); }}>
                      <select value={aclGrantee} onChange={(event) => setAclGrantee(event.target.value)} aria-label="加授成员">
                        {directory.map((entry) => <option value={entry.user.user_id} key={entry.user.user_id}>{entry.user.display_name}</option>)}
                      </select>
                      <select value={aclPermission} onChange={(event) => setAclPermission(event.target.value)} aria-label="权限">
                        <option value="chat">对话</option><option value="view">查看</option><option value="edit">编辑</option><option value="publish">发布</option>
                      </select>
                      <button disabled={!aclGrantee || busy.startsWith("acl:")}>加授权限</button>
                    </form>
                  )}
                  {acls.length > 0 && <div className={styles.aclList}>{acls.map((acl) => {
                    const profile = memberById.get(acl.granteeId)?.user;
                    return <span key={`${acl.granteeId}:${acl.permission}`}>{profile?.display_name || acl.granteeId} · {PERMISSION_LABELS[acl.permission] ?? acl.permission}{item.canManage && <button className={styles.danger} onClick={() => void removeAcl(agent.agentId, acl.granteeId, acl.permission)} disabled={busy.startsWith("acl-remove:")}>撤销</button>}</span>;
                  })}</div>}
                </article>;
              })}</div>
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
