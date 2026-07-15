"use client";

import { useEffect, useState } from "react";

interface AgentInfo {
  name: string;
  version: string;
  status: string;
  manifest_hash: string;
  created_at: string;
}

export default function AgentsPage() {
  const [agents, setAgents] = useState<AgentInfo[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    async function load() {
      try {
        const res = await fetch("/api/harness/agents");
        if (!res.ok) throw new Error(await res.text());
        setAgents(await res.json());
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e));
      } finally {
        setLoading(false);
      }
    }
    load();
  }, []);

  if (loading) {
    return (
      <div className="page-container">
        <h1>智能体列表</h1>
        <p>加载中...</p>
      </div>
    );
  }

  if (error) {
    return (
      <div className="page-container">
        <h1>智能体列表</h1>
        <p className="error-message">{error}</p>
      </div>
    );
  }

  return (
    <div className="page-container">
      <header className="page-header">
        <h1>智能体列表</h1>
      </header>

      {agents.length === 0 ? (
        <div className="empty-state">
          <span className="empty-icon" aria-hidden="true">🤖</span>
          <strong>还没有智能体</strong>
          <p>通过 CLI 发布 Agent 后，可在此查看和管理。</p>
        </div>
      ) : (
        <div className="agent-grid">
          {agents.map((agent) => (
            <div key={`${agent.name}@${agent.version}`} className="agent-card-page">
              <div className="agent-card-header">
                <span className="agent-icon" aria-hidden="true">🤖</span>
                <div>
                  <strong>{agent.name}</strong>
                  <small>v{agent.version}</small>
                </div>
              </div>
              <div className="agent-card-meta">
                <span className={`status-badge status-${agent.status}`}>
                  {agent.status}
                </span>
                <time>
                  {new Date(agent.created_at).toLocaleString("zh-CN")}
                </time>
              </div>
              <code className="agent-hash">hash: {agent.manifest_hash.slice(0, 12)}...</code>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
