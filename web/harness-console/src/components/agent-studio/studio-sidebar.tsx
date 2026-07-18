"use client";

import Link from "next/link";
import { type ReactNode, useEffect, useState } from "react";
import { ThemeToggle } from "../theme-toggle";
import {
  WorkspaceCollapseIcon,
  WorkspaceNavigation,
  type WorkspaceId,
} from "../workspace-navigation";
import styles from "./studio-sidebar.module.css";

const STORAGE_KEY = "agent-studio-sidebar-collapsed";

type StudioWorkspace = Exclude<WorkspaceId, "tasks">;

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
          <WorkspaceCollapseIcon collapsed={collapsed} />
        </button>
      </div>

      <WorkspaceNavigation active={active} collapsed={collapsed} />

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
