"use client";

import { useCallback, useSyncExternalStore } from "react";

type Locale = "zh" | "en";

const messages: Record<Locale, Record<string, string>> = {
  zh: {
    "app.title": "Agent Console",
    "nav.chat": "对话", "nav.sessions": "会话", "nav.agents": "智能体",
    "nav.dashboard": "仪表板", "nav.apiDocs": "API 文档",
    "sessions.title": "会话列表", "sessions.empty": "还没有会话",
    "sessions.emptyHint": "前往对话页面开始一个新任务。",
    "sessions.resume": "恢复", "sessions.delete": "删除",
    "agents.title": "智能体列表", "agents.empty": "还没有智能体",
    "agents.emptyHint": "通过 CLI 发布 Agent 后，可在此查看和管理。",
    "dashboard.title": "运行仪表板", "dashboard.empty": "还没有运行记录",
    "dashboard.emptyHint": "开始一个对话任务后，运行记录将显示在这里。",
    "dashboard.totalRuns": "总运行数", "dashboard.successful": "成功",
    "dashboard.failed": "失败",
    "theme.switchLight": "亮色模式", "theme.switchDark": "暗色模式",
    "notify.enable": "开启桌面通知", "notify.disable": "关闭桌面通知",
    "sidebar.recent": "最近会话",
  },
  en: {
    "app.title": "Agent Console",
    "nav.chat": "Chat", "nav.sessions": "Sessions", "nav.agents": "Agents",
    "nav.dashboard": "Dashboard", "nav.apiDocs": "API Docs",
    "sessions.title": "Sessions", "sessions.empty": "No sessions yet",
    "sessions.emptyHint": "Start a task from the chat page to create your first session.",
    "sessions.resume": "Resume", "sessions.delete": "Delete",
    "agents.title": "Agents", "agents.empty": "No agents yet",
    "agents.emptyHint": "Publish an Agent via CLI to see it here.",
    "dashboard.title": "Dashboard", "dashboard.empty": "No runs recorded yet",
    "dashboard.emptyHint": "Run history will appear here after starting a task.",
    "dashboard.totalRuns": "Total Runs", "dashboard.successful": "Succeeded",
    "dashboard.failed": "Failed",
    "theme.switchLight": "Light Mode", "theme.switchDark": "Dark Mode",
    "notify.enable": "Enable Notifications", "notify.disable": "Disable Notifications",
    "sidebar.recent": "Recent Sessions",
  },
};

let currentLocale: Locale = "zh";
const listeners = new Set<() => void>();

function getStoredLocale(): Locale {
  if (typeof window === "undefined") return "zh";
  return (window.localStorage.getItem("harness-locale") as Locale) ?? "zh";
}

// Initialize from storage
if (typeof window !== "undefined") {
  currentLocale = getStoredLocale();
}

export function setLocale(locale: Locale) {
  currentLocale = locale;
  if (typeof window !== "undefined") {
    window.localStorage.setItem("harness-locale", locale);
  }
  for (const listener of listeners) listener();
}

export function getLocale(): Locale {
  return currentLocale;
}

function subscribe(listener: () => void) {
  listeners.add(listener);
  return () => { listeners.delete(listener); };
}

export function useTranslation() {
  const locale = useSyncExternalStore(
    subscribe,
    getLocale,
    () => "zh" as Locale,
  );

  const t = useCallback(
    (key: string, vars?: Record<string, string>) => {
      let msg: string = messages[locale]?.[key] ?? key;
      if (vars) {
        for (const [k, v] of Object.entries(vars)) {
          msg = msg.replace(`{${k}}`, v);
        }
      }
      return msg;
    },
    [locale],
  );

  return { locale, setLocale, t };
}
