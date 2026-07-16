"use client";

import { useCallback, useEffect, useState } from "react";
import { AgentThread } from "../components/agent-thread";
import { AuthProvider } from "../components/auth-provider";
import { AssistantRuntimeShell } from "../components/assistant-runtime-shell";
import { DeveloperDrawer } from "../components/developer-drawer";
import { TaskSidebar } from "../components/task-sidebar";
import {
  createNewThread,
  loadOrCreateThread,
  selectThread,
} from "../lib/thread-store";

export default function Home() {
  const [threadId, setThreadId] = useState("");
  const [runDetailsOpen, setRunDetailsOpen] = useState(false);
  const [taskSidebarOpen, setTaskSidebarOpen] = useState(true);
  const [refreshToken, setRefreshToken] = useState(0);

  useEffect(() => {
    setThreadId(loadOrCreateThread(window.localStorage));
  }, []);

  function startNewTask() {
    setThreadId(createNewThread(window.localStorage));
    setRunDetailsOpen(false);
  }

  function switchTask(nextThreadId: string) {
    setThreadId(selectThread(window.localStorage, nextThreadId));
    setRunDetailsOpen(false);
  }

  const refreshCurrentTask = useCallback(() => {
    setRefreshToken((value) => value + 1);
  }, []);

  return (
    <AuthProvider>
    <main className="console-shell">
      <header className="console-header">
        <div className="brand-lockup" aria-label="智能任务助手">
          <span className="brand-mark" aria-hidden="true">
            H
          </span>
          <div>
            <h1>智能任务助手</h1>
            <p className="workspace-caption">Agent Harness</p>
          </div>
        </div>

        <div className="header-actions">
          <button
            className="icon-button"
            type="button"
            aria-pressed={runDetailsOpen}
            aria-label="切换本次运行详情"
            onClick={() => setRunDetailsOpen((current) => !current)}
          >
            <span className="details-glyph" aria-hidden="true">
              <i />
              <i />
              <i />
            </span>
            <span>{runDetailsOpen ? "收起详情" : "运行详情"}</span>
          </button>
        </div>
      </header>

      <div
        className={`workspace-stage ${taskSidebarOpen ? "tasks-open" : ""} ${runDetailsOpen ? "inspector-open" : ""}`}
      >
        <TaskSidebar
          currentThreadId={threadId}
          collapsed={!taskSidebarOpen}
          onToggle={() => setTaskSidebarOpen((current) => !current)}
          onSelect={switchTask}
          onNewTask={startNewTask}
          refreshToken={refreshToken}
          onApprovalHandled={refreshCurrentTask}
          onCurrentTaskStatusChange={refreshCurrentTask}
        />
        <section className="chat-stage" aria-label="Agent 任务对话">
          <div className="chat-surface">
            {threadId ? (
              <AssistantRuntimeShell key={`${threadId}:${refreshToken}`} threadId={threadId}>
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
    </main>
    </AuthProvider>
  );
}
