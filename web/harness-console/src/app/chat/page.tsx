"use client";

import { useEffect, useState } from "react";
import { AgentThread } from "../../components/agent-thread";
import { AssistantRuntimeShell } from "../../components/assistant-runtime-shell";
import { DeveloperDrawer } from "../../components/developer-drawer";
import { createNewThread, loadOrCreateThread } from "../../lib/thread-store";

export default function ChatPage() {
  const [threadId, setThreadId] = useState("");
  const [runDetailsOpen, setRunDetailsOpen] = useState(false);

  useEffect(() => {
    setThreadId(loadOrCreateThread(window.localStorage));
  }, []);

  function startNewTask() {
    setThreadId(createNewThread(window.localStorage));
    setRunDetailsOpen(false);
  }

  return (
    <div className="console-shell">
      <header className="console-header">
        <div className="brand-lockup" aria-label="智能任务助手">
          <span className="brand-mark" aria-hidden="true">
            H
          </span>
          <div>
            <p className="eyebrow">Agent Workspace</p>
            <h1>智能任务助手</h1>
          </div>
        </div>

        <div className="header-actions">
          <button className="quiet-button" type="button" onClick={startNewTask}>
            新任务
          </button>
          <button
            className="icon-button"
            type="button"
            aria-pressed={runDetailsOpen}
            aria-label="切换本次运行详情"
            onClick={() => setRunDetailsOpen((current) => !current)}
          >
            {runDetailsOpen ? "关闭详情" : "本次运行"}
          </button>
        </div>
      </header>

      <div className={`workspace-stage ${runDetailsOpen ? "inspector-open" : ""}`}>
        <section className="chat-stage" aria-label="Agent 任务对话">
          <div className="chat-surface">
            {threadId ? (
              <AssistantRuntimeShell key={threadId} threadId={threadId}>
                <AgentThread />
              </AssistantRuntimeShell>
            ) : (
              <div className="chat-loading" role="status" aria-busy="true">
                <div className="chat-loading-skeleton" aria-hidden="true">
                  <span className="chat-loading-avatar" />
                  <span className="chat-loading-line" />
                  <span className="chat-loading-line" />
                  <span className="chat-loading-card" />
                </div>
                <span>正在恢复任务…</span>
              </div>
            )}
          </div>
        </section>
        {runDetailsOpen && (
          <DeveloperDrawer threadId={threadId} onClose={() => setRunDetailsOpen(false)} />
        )}
      </div>
    </div>
  );
}
