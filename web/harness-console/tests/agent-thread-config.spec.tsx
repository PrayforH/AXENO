import { renderToStaticMarkup } from "react-dom/server";
import { expect, it, vi } from "vitest";

vi.mock("@assistant-ui/react-ui", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@assistant-ui/react-ui")>();
  return {
    ...actual,
    Thread: (props: {
      assistantMessage?: {
        components?: {
          ToolFallback?: React.ComponentType<Record<string, unknown>>;
        };
      };
    }) => {
      const ToolFallback = props.assistantMessage?.components?.ToolFallback;
      if (!ToolFallback) return <div>missing tool fallback</div>;
      return (
        <ToolFallback
          toolCallId="approval-tool-1"
          toolName="harness_request_approval"
          args={{
            approval_id: "approval-1",
            run_id: "run-1",
            tool_call_id: "bash-1",
            reason: "matched policy rule bash-review",
          }}
          argsText={'{"approval_id":"approval-1"}'}
        />
      );
    },
  };
});

import { AgentThread } from "../src/components/agent-thread";

it("registers the approval renderer through the assistant-ui Thread config", () => {
  const html = renderToStaticMarkup(<AgentThread />);

  expect(html).toContain("允许 Agent 执行受保护操作？");
  expect(html).toContain("批准并继续");
  expect(html).toContain("拒绝");
});
