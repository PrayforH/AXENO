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
import { loadTasks, type TaskSummary } from "../lib/task-history";

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

export function TaskSidebar({
  currentThreadId,
  collapsed,
  onToggle,
  onSelect,
  onNewTask,
  refreshToken,
  onCurrentTaskStatusChange,
}: {
  currentThreadId: string;
  collapsed: boolean;
  onToggle: () => void;
  onSelect: (task: TaskSummary) => void;
  onNewTask: () => void;
  refreshToken: number;
  onCurrentTaskStatusChange: (status: string) => void;
}) {
  const [tasks, setTasks] = useState<TaskSummary[]>([]);
  const [error, setError] = useState("");
  const runView = useRunViewModel();
  const currentStatusRef = useRef<{ threadId: string; status: string } | null>(null);

  useEffect(() => {
    approvalStore.reset();
  }, [currentThreadId]);

  useEffect(() => {
    let active = true;
    async function refresh() {
      try {
        const next = await loadTasks();
        if (active) {
          setTasks(next);
          setError("");
        }
      } catch (cause) {
        if (active) setError(cause instanceof Error ? cause.message : String(cause));
      }
    }
    void refresh();
    const timer = window.setInterval(refresh, 4_000);
    return () => {
      active = false;
      window.clearInterval(timer);
    };
  }, [refreshToken, runView?.phase]);

  const selected = useMemo(
    () => tasks.find((task) => task.thread_id === currentThreadId),
    [currentThreadId, tasks],
  );

  useEffect(() => {
    if (!selected) return;
    if (selected.pending_approval) {
      approvalStore.show(selected.pending_approval);
    } else if (runView?.phase !== "waiting_approval") {
      approvalStore.clear();
    }
  }, [runView?.phase, selected]);

  useEffect(() => {
    if (!selected) return;
    const previous = currentStatusRef.current;
    currentStatusRef.current = {
      threadId: selected.thread_id,
      status: selected.status,
    };
    if (
      previous?.threadId === selected.thread_id &&
      previous.status !== selected.status
    ) {
      onCurrentTaskStatusChange(selected.status);
    }
  }, [onCurrentTaskStatusChange, selected]);

  return (
    <aside
      className={`task-sidebar ${collapsed ? "is-collapsed" : ""}`}
      aria-label={collapsed ? "任务快捷栏" : "任务列表"}
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
            className="task-rail-toggle"
            type="button"
            onClick={onToggle}
            aria-label="展开任务列表"
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
            <button type="button" onClick={onToggle} aria-label="收起任务列表" title="收起任务列表">
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
          <div className="task-list-heading">
            <span>最近任务</span>
            <small>{tasks.length}</small>
          </div>
          <div className="task-list" role="list">
            {tasks.map((task) => (
              <button
                type="button"
                role="listitem"
                key={task.thread_id}
                className={`task-list-item ${task.thread_id === currentThreadId ? "is-active" : ""} ${task.pending_approval ? "needs-approval" : ""}`}
                onClick={() => onSelect(task)}
              >
                <span className="task-list-title">{task.title}</span>
                <span className="task-list-meta">
                  <span className={`task-status status-${task.status}`}>
                    {statusLabels[task.status] ?? task.status}
                  </span>
                  <time dateTime={task.updated_at}>{relativeTime(task.updated_at)}</time>
                </span>
              </button>
            ))}
            {tasks.length === 0 && !error && (
              <p className="task-list-empty">暂无历史任务</p>
            )}
            {error && <p className="task-list-error">任务列表暂时不可用</p>}
          </div>
          <div className="task-sidebar-account">
            <AccountMenu />
          </div>
        </>
      )}
    </aside>
  );
}
