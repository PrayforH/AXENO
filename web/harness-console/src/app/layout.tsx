import type { Metadata } from "next";
import type { ReactNode } from "react";
import "@assistant-ui/react-ui/styles/index.css";
import "@assistant-ui/react-ui/styles/markdown.css";
import "./styles.css";

export const metadata: Metadata = {
  title: "Agent Harness Console",
  description: "Local validation console for Claude Agent Harness",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="zh-CN">
      <body>{children}</body>
    </html>
  );
}
