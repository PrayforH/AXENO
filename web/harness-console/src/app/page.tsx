"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { AgentThread } from "../components/agent-thread";
import { AuthProvider, useAuth } from "../components/auth-provider";
import { AssistantRuntimeShell } from "../components/assistant-runtime-shell";
import { ContextRecoveryPanel } from "../components/context-recovery-panel";
import { DeveloperDrawer } from "../components/developer-drawer";
import { ProductivityCommandCenter } from "../components/productivity-command-center";
import { RunDetailsProvider } from "../components/run-details-context";
import {
  TaskAgentSwitcher,
  taskAgentSwitchMode,
} from "../components/task-agent-switcher";
import { TaskSidebar } from "../components/task-sidebar";
import { useRunViewModel } from "../lib/activity-store";
import { useRunStream } from "../lib/run-stream-store";
import {
  bindThreadAgent,
  createUserScopedStorage,
  createNewThread,
  loadOrCreateThread,
  loadThreadAgent,
  selectThread,
} from "../lib/thread-store";
import {
  agentItemKey,
  chatUsableAgents,
  findTaskAgent,
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
import {
  resolveTaskLaunchMode,
  type TaskThreadState,
} from "../lib/task-launch";
import type { RunActivity } from "../lib/activity-schema";

const TASK_SIDEBAR_COMPACT_QUERY = "(max-width: 820px)";

export default function Home() {
  return (
    <AuthProvider>
      <AuthenticatedHome />
    </AuthProvider>
  );
}

function AuthenticatedHome() {
  const { user } = useAuth();
  const [threadId, setThreadId] = useState("");
  const [taskAgents, setTaskAgents] = useState<TaskAgent[]>([]);
  const [selectedAgent, setSelectedAgent] = useState<TaskAgent | null>(null);
  const [modelRoutes, setModelRoutes] = useState<TaskModelRoute[]>([]);
  const [modelRouteOverride, setModelRouteOverride] = useState<string | null>(null);
  const [agentsLoading, setAgentsLoading] = useState(true);
  const [agentsError, setAgentsError] = useState("");
  const [catalogRefreshKey, setCatalogRefreshKey] = useState(0);
  const [taskSidebarOpen, setTaskSidebarOpen] = useState(true);
  const [compactTaskSidebar, setCompactTaskSidebar] = useState(false);
  const [currentThreadState, setCurrentThreadState] =
    useState<TaskThreadState>("unknown");
  const [inspectedActivity, setInspectedActivity] = useState<RunActivity | null>(null);
  const runView = useRunViewModel();
  const runStream = useRunStream();
  const currentTaskBusy = runStream.status === "running" || (
    runView?.phase === "queued" ||
    runView?.phase === "running" ||
    runView?.phase === "waiting_approval"
  );

  useEffect(() => {
    const compactViewport = window.matchMedia(TASK_SIDEBAR_COMPACT_QUERY);
    const syncCompactViewport = (matches: boolean) => {
      setCompactTaskSidebar(matches);
      if (matches) setTaskSidebarOpen(false);
    };
    syncCompactViewport(compactViewport.matches);
    const handleViewportChange = (event: MediaQueryListEvent) => {
      syncCompactViewport(event.matches);
    };
    compactViewport.addEventListener("change", handleViewportChange);
    return () => compactViewport.removeEventListener("change", handleViewportChange);
  }, []);

  useEffect(() => {
    setInspectedActivity(null);
  }, [threadId]);

  useEffect(() => {
    let active = true;
    const storage = createUserScopedStorage(window.localStorage, user.user_id);
    const storedThreadId = loadOrCreateThread(storage);
    const initialSearch = new URLSearchParams(window.location.search);
    const requestedThreadId = initialSearch.get("thread");
    const initialThreadId = requestedThreadId
      ? selectThread(storage, requestedThreadId)
      : storedThreadId;
    const hasRequestedAgent = Boolean(
      initialSearch.get("agent") &&
      initialSearch.get("version") &&
      (initialSearch.get("space") || initialSearch.get("owner")),
    );
    setThreadId(initialThreadId);
    // The concrete thread-to-Agent binding is already durable in this
    // browser. Restore it immediately so returning from Studio can mount the
    // conversation/history while the authoritative catalogs revalidate in
    // the background. Deep links deliberately wait for catalog authorization.
    const restoredBinding = hasRequestedAgent
      ? null
      : loadThreadAgent(storage, initialThreadId);
    if (restoredBinding) {
      const restoredAgent: TaskAgent = {
        ...restoredBinding,
        displayName: restoredBinding.displayName ?? restoredBinding.name,
        domain: restoredBinding.domain ?? "restored",
      };
      setSelectedAgent(restoredAgent);
      setTaskAgents([restoredAgent]);
    }
    async function loadAgentBinding() {
      setAgentsLoading(true);
      setAgentsError("");
      try {
        const [catalog, routes, taskHistory] = await Promise.all([
          loadTaskAgentCatalog(user.user_id),
          loadTaskModelRoutes().catch(() => []),
          loadTasks()
            .then((tasks) => ({ available: true as const, tasks }))
            .catch(() => ({ available: false as const, tasks: [] as TaskSummary[] })),
        ]);
        if (!active) return;
        const search = initialSearch;
        const requestedName = search.get("agent");
        const requestedVersion = search.get("version");
        const requestedSpaceId = search.get("space");
        const requestedOwnerUserId = search.get("owner");
        const requestedAgent = requestedName && requestedVersion &&
          (requestedSpaceId || requestedOwnerUserId)
          ? findTaskAgent(catalog.agents, {
              name: requestedName,
              version: requestedVersion,
              spaceId: requestedSpaceId ?? undefined,
              ownerUserId: requestedOwnerUserId ?? undefined,
            })
          : undefined;
        if (hasRequestedAgent && !requestedAgent) {
          throw new Error(
            `指定的智能体版本不可用：${requestedName}@${requestedVersion}。请返回智能体中心重新选择当前版本。`,
          );
        }
        const currentThreadId = requestedAgent
          ? createNewThread(storage)
          : initialThreadId;
        if (requestedAgent) {
          setThreadId(currentThreadId);
          window.history.replaceState({}, "", "/");
        }
        const currentTask = taskHistory.tasks.find(
          (task) => task.thread_id === currentThreadId,
        );
        setCurrentThreadState(
          currentTask ? "durable" : taskHistory.available ? "empty" : "unknown",
        );
        const stored = loadThreadAgent(storage, currentThreadId);
        const storedAgent = stored
          ? findTaskAgent(catalog.agents, stored)
          : undefined;
        const coordinates = requestedAgent ?? (currentTask
          ? {
              name: currentTask.agent_name,
              version: currentTask.agent_version,
              ownerUserId: currentTask.agent_owner_user_id,
              scope: currentTask.space_id ? "team" as const : "personal" as const,
              spaceId: currentTask.space_id ?? undefined,
            }
          : storedAgent ?? catalog.defaultAgent);
        const selected = findTaskAgent(catalog.agents, coordinates) ??
          (currentTask
            ? {
                name: coordinates.name,
                version: coordinates.version,
                displayName: coordinates.name,
                domain: "historical",
                ownerUserId: coordinates.ownerUserId,
                scope: coordinates.scope,
                spaceId: coordinates.spaceId,
              }
            : catalog.defaultAgent);
        // Task selector lists agents the user may chat with (can_chat). The
        // selected historical agent stays visible even when its grant was
        // revoked so the thread can still be read.
        const chatUsable = chatUsableAgents(catalog.agents);
        const selectedUsable = chatUsable.some(
          (agent) => agentItemKey(agent) === agentItemKey(selected),
        );
        const agents = selectedUsable
          ? chatUsable
          : currentTask
            ? [selected, ...chatUsable]
            : chatUsable;
        setTaskAgents(agents);
        setModelRoutes(routes);
        setSelectedAgent(selected);
        const storedModelRoute = loadTaskModelOverride(
          storage,
          currentThreadId,
        );
        setModelRouteOverride(
          routes.some((route) => route.id === storedModelRoute)
            ? storedModelRoute
            : null,
        );
        bindThreadAgent(storage, currentThreadId, selected);
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
  }, [catalogRefreshKey, user.user_id]);

  const availableTaskAgents = useMemo(() => taskAgents, [taskAgents]);

  useEffect(() => {
    if (runStream.threadId === threadId && runStream.runId) {
      setCurrentThreadState("durable");
    }
  }, [runStream.runId, runStream.threadId, threadId]);

  function taskStorage() {
    return createUserScopedStorage(window.localStorage, user.user_id);
  }

  const closeCompactTaskSidebar = useCallback(() => {
    if (compactTaskSidebar) setTaskSidebarOpen(false);
  }, [compactTaskSidebar]);

  const focusTaskComposer = useCallback(() => {
    closeCompactTaskSidebar();
    window.requestAnimationFrame(() => {
      document.querySelector<HTMLTextAreaElement>(".aui-composer-input")?.focus();
    });
  }, [closeCompactTaskSidebar]);

  const createTaskWithAgent = useCallback((nextAgent: TaskAgent) => {
    const storage = createUserScopedStorage(window.localStorage, user.user_id);
    const nextThreadId = createNewThread(storage);
    bindThreadAgent(storage, nextThreadId, nextAgent);
    setSelectedAgent(nextAgent);
    setThreadId(nextThreadId);
    setCurrentThreadState("empty");
    setModelRouteOverride(null);
    closeCompactTaskSidebar();
  }, [closeCompactTaskSidebar, user.user_id]);

  const startTaskWithAgent = useCallback((nextAgent: TaskAgent) => {
    const launchMode = resolveTaskLaunchMode(currentThreadState, "select-agent");
    if (launchMode === "reuse-current") {
      const storage = createUserScopedStorage(window.localStorage, user.user_id);
      bindThreadAgent(storage, threadId, nextAgent);
      setSelectedAgent(nextAgent);
      setModelRouteOverride(null);
      focusTaskComposer();
      return;
    }
    createTaskWithAgent(nextAgent);
  }, [createTaskWithAgent, currentThreadState, focusTaskComposer, threadId, user.user_id]);

  const startNewTask = useCallback(() => {
    if (!selectedAgent) return;
    const launchMode = resolveTaskLaunchMode(currentThreadState, "new-task");
    if (launchMode === "focus-current") {
      focusTaskComposer();
      return;
    }
    createTaskWithAgent(selectedAgent);
  }, [createTaskWithAgent, currentThreadState, focusTaskComposer, selectedAgent]);

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
        (agent) => agentItemKey(agent) === agentItemKey(nextAgent),
      )
    ) {
      setTaskAgents((current) => [nextAgent, ...current]);
    }
    const storage = taskStorage();
    bindThreadAgent(storage, task.thread_id, nextAgent);
    setSelectedAgent(nextAgent);
    const storedModelRoute = loadTaskModelOverride(
      storage,
      task.thread_id,
    );
    setModelRouteOverride(
      modelRoutes.some((route) => route.id === storedModelRoute)
        ? storedModelRoute
        : null,
    );
    setCurrentThreadState("durable");
    setThreadId(selectThread(storage, task.thread_id));
    closeCompactTaskSidebar();
  }

  function switchAgent(nextAgent: TaskAgent) {
    const mode = taskAgentSwitchMode(selectedAgent, nextAgent);
    if (mode === "current" || (mode === "version" && currentTaskBusy)) return;
    if (mode === "version") {
      bindThreadAgent(taskStorage(), threadId, nextAgent);
      setSelectedAgent(nextAgent);
      return;
    }
    startTaskWithAgent(nextAgent);
  }

  function openRunDetails(activity: RunActivity) {
    if (compactTaskSidebar) setTaskSidebarOpen(false);
    setInspectedActivity(activity);
  }

  return (
    <main
      className="console-shell"
      id="main-content"
      data-task-thread-state={currentThreadState}
    >
      <RunDetailsProvider
        selectedRunId={inspectedActivity?.run_id ?? null}
        onOpen={openRunDetails}
      >
      <div
        className={`workspace-stage ${taskSidebarOpen ? "tasks-open" : ""}${inspectedActivity ? " inspector-open" : ""}`}
      >
        {compactTaskSidebar && taskSidebarOpen && (
          <button
            className="task-sidebar-scrim"
            type="button"
            aria-label="关闭任务列表"
            tabIndex={-1}
            onClick={() => setTaskSidebarOpen(false)}
          />
        )}
        <TaskSidebar
          currentThreadId={threadId}
          collapsed={!taskSidebarOpen}
          overlayOpen={compactTaskSidebar && taskSidebarOpen}
          onToggle={() => {
            if (compactTaskSidebar) setInspectedActivity(null);
            setTaskSidebarOpen((current) => !current);
          }}
          onSelect={switchTask}
          onNewTask={startNewTask}
        />
        <div
          className="task-content-shell"
          aria-hidden={compactTaskSidebar && taskSidebarOpen ? true : undefined}
        >
          <header className="console-header">
            <TaskAgentSwitcher
              agents={availableTaskAgents}
              selected={selectedAgent}
              loading={agentsLoading}
              currentTaskBusy={currentTaskBusy}
              onChange={switchAgent}
            />

            <div className="header-actions">
              <ProductivityCommandCenter
                agents={availableTaskAgents}
                onNewTask={startNewTask}
                onSelectTask={switchTask}
                onStartWithAgent={startTaskWithAgent}
              />
              <ContextRecoveryPanel threadId={threadId} />
            </div>
          </header>
          <section className="chat-stage" aria-label="Agent 任务对话">
            <div className="chat-surface">
              {threadId && selectedAgent ? (
                <AssistantRuntimeShell
                  key={`${threadId}:${agentItemKey(selectedAgent)}`}
                  threadId={threadId}
                  agentName={selectedAgent.name}
                  agentVersion={selectedAgent.version}
                  agentOwnerUserId={selectedAgent.ownerUserId}
                  spaceId={selectedAgent.spaceId}
                  agentDefaultModelRoute={selectedAgent.modelRoute ?? null}
                  modelRoutes={modelRoutes}
                  modelRouteOverride={modelRouteOverride}
                  onModelRouteOverrideChange={(routeId) => {
                    saveTaskModelOverride(taskStorage(), threadId, routeId);
                    setModelRouteOverride(routeId);
                  }}
                >
                  <AgentThread userId={user.user_id} threadId={threadId} />
                </AssistantRuntimeShell>
              ) : (
                <div
                  className={`chat-loading${agentsError ? " is-error" : ""}`}
                  role={agentsError ? "alert" : "status"}
                  aria-busy={!agentsError}
                >
                  {agentsError ? (
                    <div className="chat-loading-error">
                      <strong>无法进入任务工作台</strong>
                      <span>{agentsError}</span>
                      <button
                        type="button"
                        onClick={() => setCatalogRefreshKey((current) => current + 1)}
                      >
                        重新连接
                      </button>
                    </div>
                  ) : (
                    <>
                      <div className="chat-loading-skeleton" aria-hidden="true">
                        <span className="chat-loading-avatar" />
                        <span className="chat-loading-line" />
                        <span className="chat-loading-line" />
                        <span className="chat-loading-card" />
                      </div>
                      <span>正在恢复任务与智能体版本…</span>
                    </>
                  )}
                </div>
              )}
            </div>
          </section>
        </div>
        {inspectedActivity ? (
          <DeveloperDrawer
            threadId={threadId}
            activity={inspectedActivity}
            onClose={() => setInspectedActivity(null)}
          />
        ) : null}
      </div>
      </RunDetailsProvider>
    </main>
  );
}
