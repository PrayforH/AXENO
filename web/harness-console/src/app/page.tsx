"use client";

import { CopilotChat } from "@copilotkit/react-core/v2";
import { useEffect, useState } from "react";
import { HarnessToolRenderers } from "../components/harness-tool-renderers";
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
      <HarnessToolRenderers />
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
          <div className="agent-coordinate" title="当前 Agent 版本">
            <span className="live-dot" aria-hidden="true" />
            <span>echo-agent</span>
            <code>0.1.0</code>
          </div>
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

      <section className="chat-stage" aria-label="Agent 对话">
        <div className="run-rail" aria-hidden="true">
          <span>LIVE</span>
        </div>
        <div className="chat-surface">
          {threadId ? (
            <CopilotChat
              key={threadId}
              className="harness-chat"
              agentId="harness-agent"
              threadId={threadId}
              labels={{
                chatInputPlaceholder: "描述你要让 Agent 完成的任务…",
                welcomeMessageText:
                  "开始一次真实运行。你可以直接提问，或输入 [approval] [artifact] 验证审批与产物流程。",
                chatDisclaimerText: "本地 Fake Runtime · Langfuse 默认关闭",
                assistantMessageToolbarCopyMessageLabel: "复制回答",
                assistantMessageToolbarRegenerateLabel: "重新运行",
                userMessageToolbarCopyMessageLabel: "复制消息",
                userMessageToolbarEditMessageLabel: "编辑消息",
              }}
            />
          ) : (
            <div className="chat-loading" role="status">
              正在恢复会话…
            </div>
          )}
        </div>
      </section>

      {developerMode && (
        <aside className="developer-peek" aria-label="运行详情">
          <span>THREAD</span>
          <code>{threadId || "initializing"}</code>
          <span>ROUTE</span>
          <code>/api/copilotkit → harness-agent</code>
        </aside>
      )}
    </main>
  );
}
