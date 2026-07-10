import type { Metadata } from "next";
import type { ReactNode } from "react";
import { CopilotKitShell } from "../components/copilotkit-shell";
import "./styles.css";

export const metadata: Metadata = {
  title: "Agent Harness Console",
  description: "Local validation console for Claude Agent Harness",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="zh-CN">
      <body><CopilotKitShell>{children}</CopilotKitShell></body>
    </html>
  );
}
