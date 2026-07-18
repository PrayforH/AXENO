"use client";

import { useCallback, useEffect, useState } from "react";
import { AgentThread } from "../components/agent-thread";
import { AuthProvider } from "../components/auth-provider";
import { AssistantRuntimeShell } from "../components/assistant-runtime-shell";
import { DeveloperDrawer } from "../components/developer-drawer";
import { TaskAgentSwitcher } from "../components/task-agent-switcher";
import { TaskSidebar } from "../components/task-sidebar";
import { ThemeToggle } from "../components/theme-toggle";
import {
  bindThreadAgent,
  createNewThread,
  loadOrCreateThread,
  loadThreadAgent,
  selectThread,
} from "../lib/thread-store";
import {
  loadTaskAgentCatalog,
  type TaskAgent,
} from "../lib/task-agent-catalog";
import { loadTasks, type TaskSummary } from "../lib/task-history";

export default function Home() {
  const [threadId, setThreadId] = useState("");
  const [taskAgents, setTaskAgents] = useState<TaskAgent[]>([]);
  const [selectedAgent, setSelectedAgent] = useState<TaskAgent | null>(null);
  const [agentsLoading, setAgentsLoading] = useState(true);
  const [agentsError, setAgentsError] = useState("");
  const [runDetailsOpen, setRunDetailsOpen] = useState(false);
  const [taskSidebarOpen, setTaskSidebarOpen] = useState(true);
  const [refreshToken, setRefreshToken] = useState(0);

  useEffect(() => {
    if (window.matchMedia("(max-width: 820px)").matches) {
      setTaskSidebarOpen(false);
    }
  }, []);

  useEffect(() => {
    let active = true;
    const currentThreadId = loadOrCreateThread(window.localStorage);
    setThreadId(currentThreadId);
    async function loadAgentBinding() {
      setAgentsLoading(true);
      try {
        const [catalog, tasks] = await Promise.all([
          loadTaskAgentCatalog(),
          loadTasks().catch(() => []),
        ]);
        if (!active) return;
        const currentTask = tasks.find(
          (task) => task.thread_id === currentThreadId,
        );
        const stored = loadThreadAgent(window.localStorage, currentThreadId);
        const coordinates = currentTask
          ? {
              name: currentTask.agent_name,
              version: currentTask.agent_version,
            }
          : stored ?? catalog.defaultAgent;
        const selected =
          catalog.agents.find(
            (agent) =>
              agent.name === coordinates.name &&
              agent.version === coordinates.version,
          ) ?? {
            name: coordinates.name,
            version: coordinates.version,
            displayName: stored?.displayName ?? coordinates.name,
            domain: stored?.domain ?? "historical",
          };
        const agents = catalog.agents.some(
          (agent) =>
            agent.name === selected.name && agent.version === selected.version,
        )
          ? catalog.agents
          : [selected, ...catalog.agents];
        setTaskAgents(agents);
        setSelectedAgent(selected);
        bindThreadAgent(window.localStorage, currentThreadId, selected);
        setAgentsError("");
      } catch (error) {
        if (!active) return;
        setAgentsError(
          error instanceof Error ? error.message : "智能体目录暂不可用",
        );
      } finally {
        if (active) setAgentsLoading(false);
      }
    }
    void loadAgentBinding();
    return () => {
      active = false;
    };
  }, []);

  function startNewTask() {
    if (!selectedAgent) return;
    const nextThreadId = createNewThread(window.localStorage);
    bindThreadAgent(window.localStorage, nextThreadId, selectedAgent);
    setThreadId(nextThreadId);
    setRunDetailsOpen(false);
  }

  function switchTask(task: TaskSummary) {
    const nextAgent =
      taskAgents.find(
        (agent) =>
          agent.name === task.agent_name && agent.version === task.agent_version,
      ) ?? {
        name: task.agent_name,
        version: task.agent_version,
        displayName: task.agent_name,
        domain: "historical",
      };
    if (
      !taskAgents.some(
        (agent) =>
          agent.name === nextAgent.name && agent.version === nextAgent.version,
      )
    ) {
      setTaskAgents((current) => [nextAgent, ...current]);
    }
    bindThreadAgent(window.localStorage, task.thread_id, nextAgent);
    setSelectedAgent(nextAgent);
    setThreadId(selectThread(window.localStorage, task.thread_id));
    setRunDetailsOpen(false);
  }

  function switchAgent(nextAgent: TaskAgent) {
    if (
      selectedAgent?.name === nextAgent.name &&
      selectedAgent.version === nextAgent.version
    ) {
      return;
    }
    const nextThreadId = createNewThread(window.localStorage);
    bindThreadAgent(window.localStorage, nextThreadId, nextAgent);
    setSelectedAgent(nextAgent);
    setThreadId(nextThreadId);
    setRunDetailsOpen(false);
  }

  const refreshCurrentTask = useCallback(() => {
    setRefreshToken((value) => value + 1);
  }, []);

  return (
    <AuthProvider>
    <main className="console-shell" id="main-content">
      <header className="console-header">
        <div className="brand-lockup" aria-label="Agent Studio">
          <span className="brand-mark" aria-hidden="true">
            AS
          </span>
          <div>
            <h1>Agent Studio</h1>
            <p className="workspace-caption">智能任务工作台</p>
          </div>
        </div>

        <TaskAgentSwitcher
          agents={taskAgents}
          selected={selectedAgent}
          loading={agentsLoading}
          onChange={switchAgent}
        />

        <div className="header-actions">
          <ThemeToggle />
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
            {threadId && selectedAgent ? (
              <AssistantRuntimeShell
                key={`${threadId}:${selectedAgent.name}:${selectedAgent.version}:${refreshToken}`}
                threadId={threadId}
                agentName={selectedAgent.name}
                agentVersion={selectedAgent.version}
              >
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
                <span>
                  {agentsError
                    ? `智能体目录不可用：${agentsError}`
                    : "正在恢复任务与智能体版本…"}
                </span>
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
