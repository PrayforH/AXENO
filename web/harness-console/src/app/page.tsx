"use client";

import { useEffect, useState } from "react";
import { AgentThread } from "../components/agent-thread";
import { AuthProvider } from "../components/auth-provider";
import { AssistantRuntimeShell } from "../components/assistant-runtime-shell";
import { LangfuseTraceLink } from "../components/langfuse-trace-link";
import { TaskAgentSwitcher } from "../components/task-agent-switcher";
import { TaskSidebar } from "../components/task-sidebar";
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
import {
  loadTaskModelOverride,
  loadTaskModelRoutes,
  saveTaskModelOverride,
  type TaskModelRoute,
} from "../lib/task-model-catalog";

export default function Home() {
  const [threadId, setThreadId] = useState("");
  const [taskAgents, setTaskAgents] = useState<TaskAgent[]>([]);
  const [selectedAgent, setSelectedAgent] = useState<TaskAgent | null>(null);
  const [modelRoutes, setModelRoutes] = useState<TaskModelRoute[]>([]);
  const [modelRouteOverride, setModelRouteOverride] = useState<string | null>(null);
  const [agentsLoading, setAgentsLoading] = useState(true);
  const [agentsError, setAgentsError] = useState("");
  const [taskSidebarOpen, setTaskSidebarOpen] = useState(true);

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
        const [catalog, routes, tasks] = await Promise.all([
          loadTaskAgentCatalog(),
          loadTaskModelRoutes().catch(() => []),
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
              ownerUserId: currentTask.agent_owner_user_id,
              scope: currentTask.space_id ? "team" as const : "personal" as const,
              spaceId: currentTask.space_id ?? undefined,
            }
          : stored ?? catalog.defaultAgent;
        const selected =
          catalog.agents.find((agent) =>
            agent.name === coordinates.name &&
            agent.version === coordinates.version &&
            (!coordinates.ownerUserId || agent.ownerUserId === coordinates.ownerUserId) &&
            (!coordinates.spaceId || agent.spaceId === coordinates.spaceId),
          ) ?? {
            name: coordinates.name,
            version: coordinates.version,
            displayName: stored?.displayName ?? coordinates.name,
            domain: stored?.domain ?? "historical",
            ownerUserId: coordinates.ownerUserId,
            scope: coordinates.scope,
            spaceId: coordinates.spaceId,
          };
        const agents = catalog.agents.some(
          (agent) =>
            agent.name === selected.name && agent.version === selected.version &&
            agent.ownerUserId === selected.ownerUserId && agent.spaceId === selected.spaceId,
        )
          ? catalog.agents
          : [selected, ...catalog.agents];
        setTaskAgents(agents);
        setModelRoutes(routes);
        setSelectedAgent(selected);
        const storedModelRoute = loadTaskModelOverride(
          window.localStorage,
          currentThreadId,
        );
        setModelRouteOverride(
          routes.some((route) => route.id === storedModelRoute)
            ? storedModelRoute
            : null,
        );
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
    setModelRouteOverride(null);
  }

  function switchTask(task: TaskSummary) {
    const nextAgent =
      taskAgents.find(
        (agent) =>
          agent.name === task.agent_name && agent.version === task.agent_version &&
          agent.ownerUserId === task.agent_owner_user_id &&
          agent.spaceId === (task.space_id ?? undefined),
      ) ?? {
        name: task.agent_name,
        version: task.agent_version,
        displayName: task.agent_name,
        domain: "historical",
        ownerUserId: task.agent_owner_user_id,
        scope: task.space_id ? "team" : "personal",
        spaceId: task.space_id ?? undefined,
      };
    if (
      !taskAgents.some(
        (agent) =>
          agent.name === nextAgent.name && agent.version === nextAgent.version &&
          agent.ownerUserId === nextAgent.ownerUserId && agent.spaceId === nextAgent.spaceId,
      )
    ) {
      setTaskAgents((current) => [nextAgent, ...current]);
    }
    bindThreadAgent(window.localStorage, task.thread_id, nextAgent);
    setSelectedAgent(nextAgent);
    const storedModelRoute = loadTaskModelOverride(
      window.localStorage,
      task.thread_id,
    );
    setModelRouteOverride(
      modelRoutes.some((route) => route.id === storedModelRoute)
        ? storedModelRoute
        : null,
    );
    setThreadId(selectThread(window.localStorage, task.thread_id));
  }

  function switchAgent(nextAgent: TaskAgent) {
    if (
      selectedAgent &&
      selectedAgent.name === nextAgent.name &&
      selectedAgent.version === nextAgent.version &&
      selectedAgent.ownerUserId === nextAgent.ownerUserId &&
      selectedAgent.spaceId === nextAgent.spaceId
    ) {
      return;
    }
    const nextThreadId = createNewThread(window.localStorage);
    bindThreadAgent(window.localStorage, nextThreadId, nextAgent);
    setSelectedAgent(nextAgent);
    setModelRouteOverride(null);
    setThreadId(nextThreadId);
  }

  return (
    <AuthProvider>
    <main className="console-shell" id="main-content">
      <div
        className={`workspace-stage ${taskSidebarOpen ? "tasks-open" : ""}`}
      >
        <TaskSidebar
          currentThreadId={threadId}
          collapsed={!taskSidebarOpen}
          onToggle={() => setTaskSidebarOpen((current) => !current)}
          onSelect={switchTask}
          onNewTask={startNewTask}
        />
        <div className="task-content-shell">
          <header className="console-header">
            <TaskAgentSwitcher
              agents={taskAgents}
              selected={selectedAgent}
              loading={agentsLoading}
              onChange={switchAgent}
            />

            <div className="header-actions">
              <LangfuseTraceLink />
            </div>
          </header>
          <section className="chat-stage" aria-label="Agent 任务对话">
            <div className="chat-surface">
              {threadId && selectedAgent ? (
                <AssistantRuntimeShell
                  key={`${threadId}:${selectedAgent.spaceId ?? "personal"}:${selectedAgent.ownerUserId ?? "self"}:${selectedAgent.name}:${selectedAgent.version}`}
                  threadId={threadId}
                  agentName={selectedAgent.name}
                  agentVersion={selectedAgent.version}
                  agentOwnerUserId={selectedAgent.ownerUserId}
                  spaceId={selectedAgent.spaceId}
                  agentDefaultModelRoute={selectedAgent.modelRoute ?? null}
                  modelRoutes={modelRoutes}
                  modelRouteOverride={modelRouteOverride}
                  onModelRouteOverrideChange={(routeId) => {
                    saveTaskModelOverride(window.localStorage, threadId, routeId);
                    setModelRouteOverride(routeId);
                  }}
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
        </div>
      </div>
    </main>
    </AuthProvider>
  );
}
