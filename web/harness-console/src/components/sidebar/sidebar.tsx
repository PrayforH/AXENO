"use client";

import { usePathname } from "next/navigation";
import { useTheme } from "../../lib/theme-store";
import { useRecentSessions } from "../../lib/session-store";

const navItems = [
  { href: "/chat", label: "对话", icon: "💬" },
  { href: "/sessions", label: "会话", icon: "📋" },
  { href: "/agents", label: "智能体", icon: "🤖" },
  { href: "/dashboard", label: "仪表板", icon: "📊" },
] as const;

export function Sidebar() {
  const pathname = usePathname();
  const { theme, toggleTheme } = useTheme();
  const { sessions } = useRecentSessions();

  return (
    <aside className="sidebar" aria-label="主导航">
      <div className="sidebar-brand">
        <a href="/chat" className="sidebar-brand-link">
          <span className="brand-mark" aria-hidden="true">
            H
          </span>
          <span className="sidebar-brand-text">Agent Console</span>
        </a>
      </div>

      <nav className="sidebar-nav" aria-label="页面导航">
        {navItems.map((item) => {
          const active =
            pathname === item.href || pathname.startsWith(item.href + "/");
          return (
            <a
              key={item.href}
              href={item.href}
              className={`sidebar-link ${active ? "sidebar-link--active" : ""}`}
              aria-current={active ? "page" : undefined}
            >
              <span className="sidebar-link-icon" aria-hidden="true">
                {item.icon}
              </span>
              <span>{item.label}</span>
            </a>
          );
        })}
      </nav>

      {sessions.length > 0 && (
        <div className="sidebar-recent">
          <span className="sidebar-section-label">最近会话</span>
          {sessions.slice(0, 5).map((s) => (
            <a
              key={s.session_id}
              href={`/chat`}
              className="sidebar-link sidebar-link--small"
              title={`${s.agent_name} v${s.agent_version}`}
            >
              <span className="sidebar-link-icon" aria-hidden="true">
                💬
              </span>
              <span className="sidebar-link-text">
                {s.agent_name}
                <small>v{s.agent_version}</small>
              </span>
            </a>
          ))}
        </div>
      )}

      <div className="sidebar-footer">
        <button
          type="button"
          className="sidebar-link"
          onClick={toggleTheme}
          aria-label={`切换到${theme === "light" ? "暗色" : "亮色"}模式`}
        >
          <span className="sidebar-link-icon" aria-hidden="true">
            {theme === "light" ? "🌙" : "☀️"}
          </span>
          <span>{theme === "light" ? "暗色模式" : "亮色模式"}</span>
        </button>
      </div>
    </aside>
  );
}
