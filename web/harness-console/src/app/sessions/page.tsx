"use client";

import { useEffect, useState } from "react";
import { createNewThread, loadOrCreateThread } from "../../lib/thread-store";

interface SessionInfo {
  session_id: string;
  agent_name: string;
  agent_version: string;
  created_at: string;
}

export default function SessionsPage() {
  const [sessions, setSessions] = useState<SessionInfo[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    async function load() {
      try {
        const res = await fetch("/api/harness/sessions");
        if (!res.ok) throw new Error(await res.text());
        setSessions(await res.json());
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e));
      } finally {
        setLoading(false);
      }
    }
    load();
  }, []);

  async function deleteSession(sessionId: string) {
    try {
      const res = await fetch(`/api/harness/sessions/${sessionId}`, {
        method: "DELETE",
      });
      if (!res.ok) throw new Error(await res.text());
      setSessions((prev) => prev.filter((s) => s.session_id !== sessionId));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  function resumeSession(sessionId: string) {
    const threadId = createNewThread(window.localStorage);
    window.location.href = `/chat`;
  }

  if (loading) {
    return (
      <div className="page-container">
        <h1>会话列表</h1>
        <p>加载中...</p>
      </div>
    );
  }

  if (error) {
    return (
      <div className="page-container">
        <h1>会话列表</h1>
        <p className="error-message">{error}</p>
      </div>
    );
  }

  return (
    <div className="page-container">
      <header className="page-header">
        <h1>会话列表</h1>
      </header>

      {sessions.length === 0 ? (
        <div className="empty-state">
          <span className="empty-icon" aria-hidden="true">📋</span>
          <strong>还没有会话</strong>
          <p>前往对话页面开始一个新任务。</p>
        </div>
      ) : (
        <div className="session-list">
          {sessions.map((session) => (
            <div key={session.session_id} className="session-card">
              <div className="session-card-info">
                <strong>{session.agent_name}</strong>
                <small>v{session.agent_version}</small>
                <time>
                  {new Date(session.created_at).toLocaleString("zh-CN")}
                </time>
              </div>
              <div className="session-card-actions">
                <button
                  type="button"
                  className="quiet-button"
                  onClick={() => resumeSession(session.session_id)}
                >
                  恢复
                </button>
                <button
                  type="button"
                  className="quiet-button danger"
                  onClick={() => deleteSession(session.session_id)}
                >
                  删除
                </button>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
