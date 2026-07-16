import type { Metadata } from "next";
import { AgentStudioWorkbench } from "../../../components/agent-studio/agent-studio-workbench";

export const metadata: Metadata = {
  title: "Agent Studio · Agent Harness",
  description: "构建、校验并发布领域 Agent 运行契约。",
};

export default function AgentStudioPage() {
  return <AgentStudioWorkbench />;
}
