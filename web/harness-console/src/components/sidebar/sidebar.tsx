"use client";

import { usePathname } from "next/navigation";
import { useTheme } from "../../lib/theme-store";
import { useRecentSessions } from "../../lib/session-store";
import { useTranslation } from "../../lib/i18n/use-translation";
import { useNotifications } from "../../lib/notifications";

export function Sidebar() {
  const pathname = usePathname();
  const { theme, toggleTheme } = useTheme();
  const { sessions } = useRecentSessions();
  const { locale, setLocale, t } = useTranslation();
  const { enabled, enable, disable } = useNotifications();

  const navItems = [
    { href: "/chat", label: t("nav.chat"), icon: "💬" },
    { href: "/sessions", label: t("nav.sessions"), icon: "📋" },
    { href: "/agents", label: t("nav.agents"), icon: "🤖" },
    { href: "/dashboard", label: t("nav.dashboard"), icon: "📊" },
  ];

  return (
    <aside className="sidebar" aria-label={t("nav.chat")}>
      <div className="sidebar-brand">
        <a href="/chat" className="sidebar-brand-link">
          <span className="brand-mark" aria-hidden="true">H</span>
          <span className="sidebar-brand-text">{t("app.title")}</span>
        </a>
      </div>

      <nav className="sidebar-nav" aria-label={t("nav.chat")}>
        {navItems.map((item) => {
          const active = pathname === item.href || pathname.startsWith(item.href + "/");
          return (
            <a
              key={item.href}
              href={item.href}
              className={`sidebar-link ${active ? "sidebar-link--active" : ""}`}
              aria-current={active ? "page" : undefined}
            >
              <span className="sidebar-link-icon" aria-hidden="true">{item.icon}</span>
              <span>{item.label}</span>
            </a>
          );
        })}
      </nav>

      {sessions.length > 0 && (
        <div className="sidebar-recent">
          <span className="sidebar-section-label">{t("sidebar.recent")}</span>
          {sessions.slice(0, 5).map((s) => (
            <a
              key={s.session_id}
              href="/chat"
              className="sidebar-link sidebar-link--small"
              title={`${s.agent_name} v${s.agent_version}`}
            >
              <span className="sidebar-link-icon" aria-hidden="true">💬</span>
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
          aria-label={t(theme === "light" ? "theme.switchDark" : "theme.switchLight")}
        >
          <span className="sidebar-link-icon" aria-hidden="true">
            {theme === "light" ? "🌙" : "☀️"}
          </span>
          <span>{t(theme === "light" ? "theme.switchDark" : "theme.switchLight")}</span>
        </button>

        <button
          type="button"
          className="sidebar-link"
          onClick={() => setLocale(locale === "zh" ? "en" : "zh")}
          aria-label="切换语言"
        >
          <span className="sidebar-link-icon" aria-hidden="true">🌐</span>
          <span>{locale === "zh" ? "English" : "中文"}</span>
        </button>

        <button
          type="button"
          className="sidebar-link"
          onClick={enabled ? disable : enable}
          aria-label={enabled ? t("notify.disable") : t("notify.enable")}
        >
          <span className="sidebar-link-icon" aria-hidden="true">
            {enabled ? "🔔" : "🔕"}
          </span>
          <span>{enabled ? t("notify.disable") : t("notify.enable")}</span>
        </button>

        <a
          href="http://127.0.0.1:8000/docs"
          target="_blank"
          rel="noreferrer"
          className="sidebar-link"
        >
          <span className="sidebar-link-icon" aria-hidden="true">📖</span>
          <span>{t("nav.apiDocs")}</span>
        </a>
      </div>
    </aside>
  );
}
