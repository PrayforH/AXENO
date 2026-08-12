"use client";

import Link from "next/link";
import { useEffect, useMemo, useRef, useState } from "react";
import { AccountMenu } from "./account-menu";
import {
  WorkspaceCollapseIcon,
  WorkspaceModeSwitcher,
  WorkspaceNavigation,
} from "./workspace-navigation";
import { useRunViewModel } from "../lib/activity-store";
import { approvalStore } from "../lib/approval-store";
import { useDialogFocus } from "../lib/use-dialog-focus";
import {
  loadTasks,
  setTaskArchived,
  type TaskSummary,
} from "../lib/task-history";
import { taskListRefreshDelay } from "../lib/task-list-refresh";

const statusLabels: Record<string, string> = {
  idle: "新任务",
  queued: "排队中",
  running: "运行中",
  waiting_approval: "待审批",
  cancelling: "取消中",
  cancelled: "已取消",
  succeeded: "已完成",
  failed: "失败",
  rejected: "已拒绝",
  timed_out: "已超时",
};

function relativeTime(value: string) {
  const elapsed = Math.max(0, Date.now() - new Date(value).getTime());
  if (elapsed < 60_000) return "刚刚";
  if (elapsed < 3_600_000) return `${Math.floor(elapsed / 60_000)} 分钟前`;
  if (elapsed < 86_400_000) return `${Math.floor(elapsed / 3_600_000)} 小时前`;
  return new Intl.DateTimeFormat("zh-CN", { month: "numeric", day: "numeric" }).format(
    new Date(value),
  );
}

function NewTaskIcon() {
  return (
    <svg className="task-new-icon" viewBox="0 0 20 20" aria-hidden="true">
      <rect x="3.5" y="5.5" width="11" height="11" rx="2" />
      <path d="M8 13.2 8.5 11l6.8-6.8a1.4 1.4 0 0 1 2 2L10.5 13Z" />
    </svg>
  );
}

function ArchiveIcon() {
  return (
    <svg viewBox="0 0 20 20" aria-hidden="true">
      <path d="M3.5 6.5h13v9a1.5 1.5 0 0 1-1.5 1.5H5a1.5 1.5 0 0 1-1.5-1.5Z" />
      <path d="M2.5 3.5h15v3h-15Z" />
      <path d="M7.5 10h5" />
    </svg>
  );
}

function RestoreIcon() {
  return (
    <svg viewBox="0 0 20 20" aria-hidden="true">
      <path d="M5.4 7.1H2.8V4.5" />
      <path d="M3.2 7a7 7 0 1 1-.1 5.5" />
      <path d="m3 7 2.8-2.8" />
    </svg>
  );
}

const activeStatuses = new Set(["queued", "running", "waiting_approval", "cancelling"]);

export function TaskSidebar({
  currentThreadId,
  collapsed,
  overlayOpen = false,
  onToggle,
  onSelect,
  onNewTask,
}: {
  currentThreadId: string;
  collapsed: boolean;
  overlayOpen?: boolean;
  onToggle: () => void;
  onSelect: (task: TaskSummary) => void;
  onNewTask: () => void;
}) {
  const [tasks, setTasks] = useState<TaskSummary[]>([]);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [refreshKey, setRefreshKey] = useState(0);
  const [query, setQuery] = useState("");
  const [updatingThreadId, setUpdatingThreadId] = useState("");
  const [listMode, setListMode] = useState<"recent" | "archived">("recent");
  const taskListsRef = useRef<Record<"recent" | "archived", TaskSummary[]>>({
    recent: [],
    archived: [],
  });
  const sidebarRef = useRef<HTMLElement>(null);
  const closeButtonRef = useRef<HTMLButtonElement>(null);
  const expandButtonRef = useRef<HTMLButtonElement>(null);
  const wasOverlayOpenRef = useRef(false);
  const runView = useRunViewModel();
  const showingArchived = listMode === "archived";

  useDialogFocus({
    open: overlayOpen,
    panelRef: sidebarRef,
    initialFocusRef: closeButtonRef,
    onEscape: onToggle,
  });

  useEffect(() => {
    if (overlayOpen) {
      wasOverlayOpenRef.current = true;
      return;
    }
    if (!wasOverlayOpenRef.current) return;
    wasOverlayOpenRef.current = false;
    const focusTimer = window.setTimeout(() => expandButtonRef.current?.focus(), 20);
    return () => window.clearTimeout(focusTimer);
  }, [overlayOpen]);

  useEffect(() => {
    approvalStore.reset(currentThreadId);
  }, [currentThreadId]);

  useEffect(() => {
    let active = true;
    let refreshing = false;
    let timer: number | undefined;

    function schedule(next: TaskSummary[], failed = false) {
      if (!active || document.visibilityState === "hidden") return;
      window.clearTimeout(timer);
      timer = window.setTimeout(
        () => void refresh(),
        taskListRefreshDelay(
          next.map((task) => task.status),
          runView?.phase,
          failed,
        ),
      );
    }

    async function refresh() {
      if (
        !active
        || refreshing
        || document.visibilityState === "hidden"
      ) return;
      refreshing = true;
      try {
        const next = await loadTasks(showingArchived);
        if (active) {
          taskListsRef.current[listMode] = next;
          setTasks(next);
          setError("");
          schedule(next);
        }
      } catch (cause) {
        if (active) {
          setError(cause instanceof Error ? cause.message : String(cause));
          schedule([], true);
        }
      } finally {
        refreshing = false;
        if (active) setLoading(false);
      }
    }

    function refreshWhenVisible() {
      if (document.visibilityState === "hidden") {
        window.clearTimeout(timer);
        return;
      }
      window.clearTimeout(timer);
      void refresh();
    }

    refreshWhenVisible();
    document.addEventListener("visibilitychange", refreshWhenVisible);
    window.addEventListener("focus", refreshWhenVisible);
    return () => {
      active = false;
      window.clearTimeout(timer);
      document.removeEventListener("visibilitychange", refreshWhenVisible);
      window.removeEventListener("focus", refreshWhenVisible);
    };
  }, [listMode, refreshKey, runView?.phase, showingArchived]);

  function switchListMode(next: "recent" | "archived") {
    if (next === listMode) return;
    const cached = taskListsRef.current[next];
    setListMode(next);
    setTasks(cached);
    setQuery("");
    setError("");
    setLoading(cached.length === 0);
  }

  function retryTasks() {
    setError("");
    setLoading(true);
    setRefreshKey((current) => current + 1);
  }

  async function updateArchived(task: TaskSummary, archived: boolean) {
    if (activeStatuses.has(task.status)) return;
    setUpdatingThreadId(task.thread_id);
    try {
      await setTaskArchived(task.thread_id, archived);
      setTasks((current) => {
        const next = current.filter((item) => item.thread_id !== task.thread_id);
        taskListsRef.current[listMode] = next;
        return next;
      });
      const destinationMode = archived ? "archived" : "recent";
      taskListsRef.current[destinationMode] = [
        task,
        ...taskListsRef.current[destinationMode].filter(
          (item) => item.thread_id !== task.thread_id,
        ),
      ];
      setError("");
      if (archived) {
        if (task.thread_id === currentThreadId) onNewTask();
      } else {
        setListMode("recent");
        setTasks(taskListsRef.current.recent);
        setLoading(false);
        onSelect(task);
      }
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setUpdatingThreadId("");
    }
  }

  const selected = useMemo(
    () => tasks.find((task) => task.thread_id === currentThreadId),
    [currentThreadId, tasks],
  );
  const filteredTasks = useMemo(() => {
    const normalized = query.trim().toLocaleLowerCase();
    if (!normalized) return tasks;
    return tasks.filter((task) =>
      [task.title, statusLabels[task.status] ?? task.status, task.agent_name]
        .join(" ")
        .toLocaleLowerCase()
        .includes(normalized),
    );
  }, [query, tasks]);

  useEffect(() => {
    if (!selected) return;
    if (selected.pending_approval) {
      approvalStore.show(selected.pending_approval, selected.thread_id);
    } else if (runView?.phase !== "waiting_approval") {
      approvalStore.clear(undefined, selected.thread_id);
    }
  }, [runView?.phase, selected]);

  return (
    <aside
      ref={sidebarRef}
      className={`task-sidebar ${collapsed ? "is-collapsed" : ""}`}
      aria-label={collapsed ? "任务快捷栏" : "任务列表"}
      aria-modal={overlayOpen ? true : undefined}
      data-task-sidebar-overlay={overlayOpen ? "true" : undefined}
      role={overlayOpen ? "dialog" : undefined}
    >
      {collapsed ? (
        <div className="task-sidebar-rail">
          <Link
            className="task-rail-brand"
            href="/"
            aria-label="Agent Studio 任务首页"
          >
            AS
          </Link>
          <button
            ref={expandButtonRef}
            className="task-rail-toggle"
            type="button"
            onClick={onToggle}
            aria-label="展开任务列表"
            aria-expanded="false"
            title="展开任务列表"
          >
            <WorkspaceCollapseIcon collapsed />
          </button>
          <WorkspaceNavigation active="tasks" collapsed />
          <button
            className="task-rail-action"
            type="button"
            onClick={onNewTask}
            aria-label="新建任务"
            title="新建任务"
          >
            <NewTaskIcon />
          </button>
          <div className="task-rail-account">
            <AccountMenu />
          </div>
        </div>
      ) : (
        <>
          <div className="task-sidebar-brand">
            <Link className="task-sidebar-brand-link" href="/" aria-label="Agent Studio 任务首页">
              <span className="task-sidebar-brand-mark" aria-hidden="true">AS</span>
              <span className="task-sidebar-brand-copy">
                <strong>Agent Studio</strong>
                <small>智能任务工作台</small>
              </span>
            </Link>
            <button
              ref={closeButtonRef}
              type="button"
              onClick={onToggle}
              aria-label="收起任务列表"
              aria-expanded="true"
              title="收起任务列表"
            >
              <WorkspaceCollapseIcon collapsed={false} />
            </button>
          </div>
          <div className="task-sidebar-mode">
            <WorkspaceModeSwitcher mode="tasks" />
          </div>
          <div className="task-sidebar-primary">
            <button type="button" onClick={onNewTask}>
              <NewTaskIcon />
              <span>新建任务</span>
            </button>
          </div>
          <div className="task-list-toolbar">
            <div className="task-list-scope" role="tablist" aria-label="任务范围">
              <button
                type="button"
                role="tab"
                aria-selected={!showingArchived}
                onClick={() => switchListMode("recent")}
              >
                最近
              </button>
              <button
                type="button"
                role="tab"
                aria-selected={showingArchived}
                onClick={() => switchListMode("archived")}
              >
                已归档
              </button>
            </div>
            <div className="task-list-heading">
              <span>{showingArchived ? "已归档任务" : "最近任务"}</span>
              <small>{query ? `${filteredTasks.length} / ${tasks.length}` : tasks.length}</small>
            </div>
            <label className="task-list-search">
              <span aria-hidden="true" />
              <input
                type="search"
                value={query}
                placeholder="搜索任务或智能体"
                aria-label={showingArchived ? "搜索已归档任务" : "搜索最近任务"}
                onChange={(event) => setQuery(event.target.value)}
              />
            </label>
          </div>
          <div className="task-list" role="list">
            {filteredTasks.map((task) => (
              <div
                role="listitem"
                key={task.thread_id}
                className="task-list-row"
              >
                <button
                  type="button"
                  className={`task-list-item ${!showingArchived && task.thread_id === currentThreadId ? "is-active" : ""} ${task.pending_approval ? "needs-approval" : ""}`}
                  onClick={() => showingArchived
                    ? void updateArchived(task, false)
                    : onSelect(task)}
                >
                  <span className="task-list-title">{task.title}</span>
                  <span className="task-list-meta">
                    <span className={`task-status status-${task.status}`}>
                      {statusLabels[task.status] ?? task.status}
                    </span>
                    <time dateTime={task.updated_at}>{relativeTime(task.updated_at)}</time>
                  </span>
                </button>
                <button
                  type="button"
                  className="task-list-archive"
                  onClick={() => void updateArchived(task, !showingArchived)}
                  disabled={
                    updatingThreadId === task.thread_id
                    || activeStatuses.has(task.status)
                  }
                  aria-label={showingArchived
                    ? `恢复并打开 ${task.title}`
                    : `归档 ${task.title}`}
                  title={
                    activeStatuses.has(task.status)
                      ? "任务结束后可归档"
                      : showingArchived
                        ? "恢复并打开任务"
                        : "归档任务"
                  }
                >
                  {showingArchived ? <RestoreIcon /> : <ArchiveIcon />}
                </button>
              </div>
            ))}
            {loading && tasks.length === 0 && (
              <div className="task-list-state" aria-live="polite">
                <span className="task-list-spinner" aria-hidden="true" />
                <strong>{showingArchived ? "正在读取归档" : "正在读取任务"}</strong>
                <small>{showingArchived ? "同步已归档的任务记录…" : "同步最近的对话与运行状态…"}</small>
              </div>
            )}
            {!loading && tasks.length === 0 && !error && (
              <div className="task-list-state task-list-empty">
                <strong>{showingArchived ? "还没有归档任务" : "从第一个任务开始"}</strong>
                <small>
                  {showingArchived
                    ? "归档的任务会保留在这里，可随时恢复。"
                    : "描述目标，Agent 会规划步骤并保留执行记录。"}
                </small>
                <button
                  type="button"
                  onClick={() => showingArchived ? switchListMode("recent") : onNewTask()}
                >
                  {showingArchived ? "回到最近任务" : "开始新任务"}
                </button>
              </div>
            )}
            {!loading && tasks.length > 0 && filteredTasks.length === 0 && (
              <div className="task-list-state task-list-empty">
                <strong>没有匹配的任务</strong>
                <small>换一个标题、状态或智能体名称试试。</small>
                <button type="button" onClick={() => setQuery("")}>清除搜索</button>
              </div>
            )}
            {error && (
              <div className="task-list-state task-list-error" role="alert">
                <strong>{showingArchived ? "归档列表暂时不可用" : "任务列表暂时不可用"}</strong>
                <small>当前任务不受影响，可以重新连接历史记录。</small>
                <button type="button" onClick={retryTasks}>重新加载</button>
              </div>
            )}
          </div>
          <div className="task-sidebar-account">
            <AccountMenu />
          </div>
        </>
      )}
    </aside>
  );
}
