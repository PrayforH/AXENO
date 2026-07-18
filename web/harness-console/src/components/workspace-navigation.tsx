import Link from "next/link";
import styles from "./workspace-navigation.module.css";

export type WorkspaceId = "tasks" | "agents" | "usage" | "data";

export const workspaceItems: ReadonlyArray<{
  id: WorkspaceId;
  href: string;
  label: string;
}> = [
  { id: "tasks", href: "/", label: "任务" },
  { id: "agents", href: "/studio/agents", label: "智能体" },
  { id: "usage", href: "/studio/usage", label: "用量" },
  { id: "data", href: "/studio/data", label: "数据" },
];

export function WorkspaceIcon({ workspace }: { workspace: WorkspaceId }) {
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

export function WorkspaceCollapseIcon({
  collapsed,
}: {
  collapsed: boolean;
}) {
  return (
    <svg className={styles.collapseIcon} viewBox="0 0 20 20" aria-hidden="true">
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

export function WorkspaceNavigation({
  active,
  collapsed = false,
}: {
  active: WorkspaceId;
  collapsed?: boolean;
}) {
  return (
    <nav
      className={styles.navigation}
      data-workspace-navigation={collapsed ? "collapsed" : "expanded"}
      aria-label="工作区"
    >
      {workspaceItems.map((workspace) => {
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
  );
}
