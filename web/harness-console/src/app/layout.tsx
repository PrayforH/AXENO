import type { Metadata, Viewport } from "next";
import type { ReactNode } from "react";
import "@assistant-ui/react-ui/styles/index.css";
import "@assistant-ui/react-ui/styles/markdown.css";
import "./styles.css";
import "./codex-theme.css";

export const metadata: Metadata = {
  title: {
    default: "Agent Studio",
    template: "%s · Agent Studio",
  },
  description: "面向业务 Agent 的任务与控制工作台",
};

export const viewport: Viewport = {
  colorScheme: "light dark",
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: "#f7f7f7" },
    { media: "(prefers-color-scheme: dark)", color: "#181818" },
  ],
};

const colorModeScript = `
(() => {
  const key = "agent-harness-color-mode";
  try {
    const stored = window.localStorage.getItem(key);
    const mode = stored === "light" || stored === "dark"
      ? stored
      : window.matchMedia("(prefers-color-scheme: dark)").matches
        ? "dark"
        : "light";
    document.documentElement.dataset.colorMode = mode;
    document.documentElement.style.colorScheme = mode;
  } catch {
    document.documentElement.dataset.colorMode = "dark";
    document.documentElement.style.colorScheme = "dark";
  }
})();
`;

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html
      lang="zh-CN"
      data-theme="codex-theme-v1"
      data-color-mode="dark"
      suppressHydrationWarning
    >
      <head>
        <script dangerouslySetInnerHTML={{ __html: colorModeScript }} />
      </head>
      <body className="codex-theme-v1">
        <a className="skip-link" href="#main-content">
          跳到主要内容
        </a>
        {children}
      </body>
    </html>
  );
}
