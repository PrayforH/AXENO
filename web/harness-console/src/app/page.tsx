"use client";

import { useEffect, useState } from "react";
import { AgentThread } from "../components/agent-thread";
import { AssistantRuntimeShell } from "../components/assistant-runtime-shell";
import { DeveloperDrawer } from "../components/developer-drawer";
import { createNewThread, loadOrCreateThread } from "../lib/thread-store";

export default function Home() {
  const [threadId, setThreadId] = useState("");
  const [developerMode, setDeveloperMode] = useState(false);

  useEffect(() => {
    setThreadId(loadOrCreateThread(window.localStorage));
  }, []);

  function startNewConversation() {
    setThreadId(createNewThread(window.localStorage));
  }

  return (
    <main className="console-shell">
      <header className="console-header">
        <div className="brand-lockup" aria-label="Claude Agent Harness Console">
          <span className="brand-mark" aria-hidden="true">
            H
          </span>
          <div>
            <p className="eyebrow">Agent Harness</p>
            <h1>交互验证台</h1>
          </div>
        </div>

        <div className="header-actions">
          <button className="quiet-button" type="button" onClick={startNewConversation}>
            新对话
          </button>
          <button
            className="icon-button"
            type="button"
            aria-pressed={developerMode}
            aria-label="切换开发者信息"
            onClick={() => setDeveloperMode((current) => !current)}
          >
            {developerMode ? "关闭详情" : "运行详情"}
          </button>
        </div>
      </header>

      <div className={`workspace-stage ${developerMode ? "inspector-open" : ""}`}>
        <section className="chat-stage" aria-label="Agent 对话">
          <div className="chat-surface">
            {threadId ? (
              <AssistantRuntimeShell key={threadId} threadId={threadId}>
                <AgentThread />
              </AssistantRuntimeShell>
            ) : (
              <div className="chat-loading" role="status">
                正在恢复会话…
              </div>
            )}
          </div>
        </section>
        {developerMode && (
          <DeveloperDrawer threadId={threadId} onClose={() => setDeveloperMode(false)} />
        )}
      </div>
    </main>
  );
}
