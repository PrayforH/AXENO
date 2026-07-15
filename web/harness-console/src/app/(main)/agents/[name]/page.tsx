"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";

interface AgentInfo {
  name: string;
  version: string;
  status: string;
  manifest_hash: string;
  created_at: string;
  snapshot?: Record<string, unknown>;
}

export default function AgentDetailPage() {
  const params = useParams<{ name: string }>();
  const name = decodeURIComponent(params.name);
  const [versions, setVersions] = useState<AgentInfo[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [selectedVersion, setSelectedVersion] = useState<AgentInfo | null>(null);

  useEffect(() => {
    async function load() {
      try {
        const res = await fetch(`/api/harness/agents/${encodeURIComponent(name)}`);
        if (!res.ok) throw new Error(await res.text());
        const data: AgentInfo[] = await res.json();
        setVersions(data);
        if (data.length > 0) setSelectedVersion(data[0]);
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e));
      } finally {
        setLoading(false);
      }
    }
    load();
  }, [name]);

  if (loading) {
    return <div className="page-container"><p>加载中...</p></div>;
  }

  if (error) {
    return <div className="page-container"><p className="error-message">{error}</p></div>;
  }

  return (
    <div className="page-container">
      <header className="page-header">
        <a href="/agents" className="back-link">← 返回智能体列表</a>
        <h1>{name}</h1>
      </header>

      <div className="agent-detail-grid">
        <section className="agent-versions-panel">
          <h2>版本历史</h2>
          {versions.length === 0 ? (
            <p className="muted">暂无版本。</p>
          ) : (
            <div className="version-list">
              {versions.map((v) => (
                <button
                  key={v.version}
                  type="button"
                  className={`version-item ${selectedVersion?.version === v.version ? "version-item--active" : ""}`}
                  onClick={() => setSelectedVersion(v)}
                >
                  <strong>v{v.version}</strong>
                  <span className={`status-badge status-${v.status}`}>{v.status}</span>
                  <time>{new Date(v.created_at).toLocaleString("zh-CN")}</time>
                </button>
              ))}
            </div>
          )}
        </section>

        <section className="agent-detail-panel">
          {selectedVersion ? (
            <>
              <h2>版本详情</h2>
              <dl className="detail-meta">
                <div><dt>版本</dt><dd>v{selectedVersion.version}</dd></div>
                <div><dt>状态</dt><dd><span className={`status-badge status-${selectedVersion.status}`}>{selectedVersion.status}</span></dd></div>
                <div><dt>哈希</dt><dd><code>{selectedVersion.manifest_hash.slice(0, 24)}...</code></dd></div>
                <div><dt>发布</dt><dd>{new Date(selectedVersion.created_at).toLocaleString("zh-CN")}</dd></div>
              </dl>

              {selectedVersion.snapshot && (
                <details className="manifest-preview">
                  <summary>完整 Manifest</summary>
                  <pre className="manifest-code">
                    <code>
                      {JSON.stringify(selectedVersion.snapshot, null, 2)}
                    </code>
                  </pre>
                </details>
              )}
            </>
          ) : (
            <p className="muted">选择一个版本查看详情。</p>
          )}
        </section>
      </div>
    </div>
  );
}
