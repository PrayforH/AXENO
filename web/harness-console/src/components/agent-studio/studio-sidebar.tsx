"use client";

import Link from "next/link";
import { type ReactNode, useEffect, useState } from "react";
import { ThemeToggle } from "../theme-toggle";
import styles from "./studio-sidebar.module.css";

const STORAGE_KEY = "agent-studio-sidebar-collapsed";

type StudioWorkspace = "agents" | "usage" | "data";

const workspaces: Array<{
  id: "tasks" | StudioWorkspace;
  href: string;
  label: string;
}> = [
  { id: "tasks", href: "/", label: "任务" },
  { id: "agents", href: "/studio/agents", label: "智能体" },
  { id: "usage", href: "/studio/usage", label: "用量" },
  { id: "data", href: "/studio/data", label: "数据" },
];

function WorkspaceIcon({
  workspace,
}: {
  workspace: "tasks" | StudioWorkspace;
}) {
  if (workspace === "tasks") {
    return (
      <svg viewBox="0 0 20 20" aria-hidden="true">
        <path d="M4.5 5.5h11M4.5 10h11M4.5 14.5h7" />
      </svg>
    );
  }
  if (workspace === "agents") {
    return (
      <svg viewBox="0 0 20 20" aria-hidden="true">
        <circle cx="6" cy="6" r="2" />
        <circle cx="14" cy="6" r="2" />
        <circle cx="10" cy="14" r="2" />
        <path d="m7.7 7.1 1.4 4.8m3.2-4.8-1.4 4.8M8 6h4" />
      </svg>
    );
  }
  if (workspace === "usage") {
    return (
      <svg viewBox="0 0 20 20" aria-hidden="true">
        <path d="M4.5 15.5V11h3v4.5m2-8v8h3v-8m2-3v11h3v-11" />
      </svg>
    );
  }
  return (
    <svg viewBox="0 0 20 20" aria-hidden="true">
      <ellipse cx="10" cy="5.5" rx="5.5" ry="2.5" />
      <path d="M4.5 5.5v4c0 1.4 2.5 2.5 5.5 2.5s5.5-1.1 5.5-2.5v-4m-11 4v4c0 1.4 2.5 2.5 5.5 2.5s5.5-1.1 5.5-2.5v-4" />
    </svg>
  );
}

function CollapseIcon({ collapsed }: { collapsed: boolean }) {
  return (
    <svg viewBox="0 0 20 20" aria-hidden="true">
      <path
        d={
          collapsed
            ? "m8.5 4 6 6-6 6m-5-12 6 6-6 6"
            : "m11.5 4-6 6 6 6m5-12-6 6 6 6"
        }
      />
    </svg>
  );
}

export function StudioSidebar({
  active,
  children,
  footer,
}: {
  active: StudioWorkspace;
  children?: ReactNode;
  footer?: ReactNode;
}) {
  const [collapsed, setCollapsed] = useState(false);

  useEffect(() => {
    try {
      const stored = window.localStorage.getItem(STORAGE_KEY);
      setCollapsed(
        stored === "true" ||
          (stored === null &&
            window.matchMedia("(max-width: 980px)").matches),
      );
    } catch {
      setCollapsed(window.matchMedia("(max-width: 980px)").matches);
    }
  }, []);

  function toggleSidebar() {
    setCollapsed((current) => {
      const next = !current;
      try {
        window.localStorage.setItem(STORAGE_KEY, String(next));
      } catch {
        // The layout still works when storage is unavailable.
      }
      return next;
    });
  }

  return (
    <aside
      className={styles.sidebar}
      data-studio-sidebar={collapsed ? "collapsed" : "expanded"}
      aria-label={
        collapsed ? "Agent Studio 快捷栏" : "Agent Studio 控制面导航"
      }
    >
      <header className={styles.brand}>
        <Link
          className={styles.brandLink}
          href="/studio/agents"
          aria-label="Agent Studio 首页"
        >
          <span className={styles.brandMark} aria-hidden="true">
            AS
          </span>
          {!collapsed && (
            <span className={styles.brandCopy}>
              <strong>Agent Studio</strong>
              <small>智能体控制面</small>
            </span>
          )}
        </Link>
      </header>

      <div className={styles.toolbar}>
        {!collapsed && <span>工作区</span>}
        <button
          className={styles.collapseButton}
          type="button"
          aria-expanded={!collapsed}
          aria-label={
            collapsed ? "展开 Agent Studio 侧栏" : "收起 Agent Studio 侧栏"
          }
          title={collapsed ? "展开侧栏" : "收起侧栏"}
          onClick={toggleSidebar}
        >
          <CollapseIcon collapsed={collapsed} />
        </button>
      </div>

      <nav className={styles.navigation} aria-label="Agent Studio 工作区">
        {workspaces.map((workspace) => {
          const current = workspace.id === active;
          return (
            <Link
              className={current ? styles.navigationActive : styles.navigationLink}
              href={workspace.href}
              aria-current={current ? "page" : undefined}
              title={collapsed ? workspace.label : undefined}
              key={workspace.id}
            >
              <WorkspaceIcon workspace={workspace.id} />
              {!collapsed && <span>{workspace.label}</span>}
            </Link>
          );
        })}
      </nav>

      {!collapsed && children && (
        <div className={styles.sidebarBody}>{children}</div>
      )}

      <footer className={styles.sidebarFooter}>
        {!collapsed && footer && (
          <div className={styles.footerContent}>{footer}</div>
        )}
        <ThemeToggle className={styles.themeToggle} />
      </footer>
    </aside>
  );
}
