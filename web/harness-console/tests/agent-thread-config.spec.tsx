import { renderToStaticMarkup } from "react-dom/server";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { expect, it, vi } from "vitest";

vi.mock("@assistant-ui/react-ui", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@assistant-ui/react-ui")>();
  const ThreadWelcome = Object.assign(
    ({ children }: { children?: React.ReactNode }) => <div>{children}</div>,
    {
      Root: ({ children }: { children?: React.ReactNode }) => <div>{children}</div>,
      Center: ({ children }: { children?: React.ReactNode }) => <div>{children}</div>,
      Avatar: () => <div>H</div>,
      Message: () => null,
      Suggestions: () => null,
      Suggestion: ({
        suggestion,
      }: {
        suggestion: { text?: React.ReactNode; prompt: string };
      }) => <button type="button">{suggestion.text ?? suggestion.prompt}</button>,
    },
  );
  return {
    ...actual,
    ThreadWelcome,
    Thread: (props: {
      assistantMessage?: {
        components?: {
          ToolFallback?: React.ComponentType<Record<string, unknown>>;
        };
      };
      components?: {
        ThreadWelcome?: React.ComponentType;
      };
    }) => {
      const ToolFallback = props.assistantMessage?.components?.ToolFallback;
      const Welcome = props.components?.ThreadWelcome;
      if (!ToolFallback) return <div>missing tool fallback</div>;
      return (
        <>
          {Welcome && <Welcome />}
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
        </>
      );
    },
  };
});

import { AgentThread } from "../src/components/agent-thread";

const agentThreadSource = readFileSync(
  join(process.cwd(), "src/components/agent-thread.tsx"),
  "utf8",
);

it("registers the approval renderer through the assistant-ui Thread config", () => {
  const html = renderToStaticMarkup(<AgentThread />);

  expect(html).toContain("允许 Agent 执行受保护操作？");
  expect(html).toContain("批准并继续");
  expect(html).toContain("拒绝");
});

it("presents task-first guidance through a custom assistant-ui welcome", () => {
  const html = renderToStaticMarkup(<AgentThread />);

  expect(html).toContain("今天想让 Agent 完成什么？");
  expect(html).toContain("分析与规划");
  expect(html).toContain("阅读与整理");
  expect(html).toContain("执行与协作");
  expect(html).toContain("关键操作会先请求确认");
});

it("uses the current run control name in incomplete-run guidance", () => {
  expect(agentThreadSource).toContain("请打开“本次运行”查看详情");
  expect(agentThreadSource).not.toContain("请查看运行详情");
});
