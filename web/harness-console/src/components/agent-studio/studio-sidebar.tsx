"use client";

import Link from "next/link";
import { type ReactNode, useEffect, useState } from "react";
import { AccountMenu } from "../account-menu";
import {
  WorkspaceCollapseIcon,
  WorkspaceNavigation,
  type WorkspaceId,
} from "../workspace-navigation";
import styles from "./studio-sidebar.module.css";

const STORAGE_KEY = "agent-studio-sidebar-collapsed";
const COMPACT_MEDIA_QUERY = "(max-width: 980px)";

type StudioWorkspace = Exclude<WorkspaceId, "tasks">;

export function StudioSidebar({
  active,
  children,
}: {
  active: StudioWorkspace;
  children?: ReactNode;
}) {
  const [collapsed, setCollapsed] = useState(false);

  useEffect(() => {
    const compactViewport = window.matchMedia(COMPACT_MEDIA_QUERY);

    function syncSidebarToViewport() {
      if (compactViewport.matches) {
        setCollapsed(true);
        return;
      }

      try {
        setCollapsed(window.localStorage.getItem(STORAGE_KEY) === "true");
      } catch {
        setCollapsed(false);
      }
    }

    syncSidebarToViewport();
    compactViewport.addEventListener("change", syncSidebarToViewport);
    return () => {
      compactViewport.removeEventListener("change", syncSidebarToViewport);
    };
  }, []);

  function toggleSidebar() {
    setCollapsed((current) => {
      const next = !current;
      if (!window.matchMedia(COMPACT_MEDIA_QUERY).matches) {
        try {
          window.localStorage.setItem(STORAGE_KEY, String(next));
        } catch {
          // The layout still works when storage is unavailable.
        }
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
        {!collapsed && (
          <button
            className={styles.collapseButton}
            type="button"
            aria-expanded={!collapsed}
            aria-label="收起 Agent Studio 侧栏"
            title="收起侧栏"
            onClick={toggleSidebar}
          >
            <WorkspaceCollapseIcon collapsed={false} />
          </button>
        )}
      </header>

      {collapsed && (
        <div className={styles.toolbar}>
          <div className={styles.toolbarActions}>
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
        </div>
      )}

      <WorkspaceNavigation
        active={active}
        collapsed={collapsed}
        visible={["tasks", "agents", "capabilities", "knowledge", "spaces"]}
      />

      {!collapsed && children && (
        <div className={styles.sidebarBody}>{children}</div>
      )}

      <footer className={styles.sidebarFooter}>
        <div className={styles.accountSlot}>
          <AccountMenu />
        </div>
      </footer>
    </aside>
  );
}
