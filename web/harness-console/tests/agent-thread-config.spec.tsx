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

import {
  AgentThread,
  hasCurrentTurnAssistantText,
  inputArtifactDownloadHref,
  isIntermediateAssistantMessage,
} from "../src/components/agent-thread";

const agentThreadSource = readFileSync(
  join(process.cwd(), "src/components/agent-thread.tsx"),
  "utf8",
);

it("registers the approval renderer through the assistant-ui Thread config", () => {
  const html = renderToStaticMarkup(<AgentThread />);

  expect(html).toContain("允许执行这个操作？");
  expect(html).toContain("允许并继续");
  expect(html).toContain("拒绝");
});

it("presents task-first guidance through a custom assistant-ui welcome", () => {
  const html = renderToStaticMarkup(<AgentThread />);

  expect(html).toContain("把目标交给 Agent");
  expect(html).toContain("分析与规划");
  expect(html).toContain("阅读与整理");
  expect(html).toContain("执行与协作");
  expect(html).toContain("在关键操作前请求确认");
});

it("uses the current run control name in incomplete-run guidance", () => {
  expect(agentThreadSource).toContain("可打开“运行详情”查看原因");
  expect(agentThreadSource).not.toContain("请查看运行详情");
});

it("keeps sandbox and keyboard guidance adjacent to the composer", () => {
  expect(agentThreadSource).toContain('className="composer-meta"');
  expect(agentThreadSource).toContain("隔离工作区");
  expect(agentThreadSource).toContain("Enter 发送 · Shift + Enter 换行");
  expect(agentThreadSource).toContain("处理审批后，Agent 会从当前步骤继续");
});

it("keeps assistant output avatar-free so activity rows cannot overlap it", () => {
  expect(agentThreadSource).not.toContain("<AssistantMessage.Avatar />");
  expect(agentThreadSource).not.toContain("assistantAvatar=");
});

it("places copy before edit below the user message content", () => {
  const content = agentThreadSource.indexOf("<UserMessage.Content />");
  const actions = agentThreadSource.indexOf("<ActionBarPrimitive.Root", content);
  const copy = agentThreadSource.indexOf("<ActionBarPrimitive.Copy", actions);
  const edit = agentThreadSource.indexOf('aria-label="编辑消息"', actions);
  expect(content).toBeGreaterThan(-1);
  expect(actions).toBeGreaterThan(content);
  expect(copy).toBeGreaterThan(actions);
  expect(edit).toBeGreaterThan(copy);
  expect(agentThreadSource).toContain("onClick={beginEdit}");
  expect(agentThreadSource).toContain("<ActionBarPrimitive.Copy");
  expect(agentThreadSource).toContain('aria-label="编辑消息"');
  expect(agentThreadSource).toContain('aria-label="复制消息"');
});

it("only edits the latest user turn and allows unchanged text to start a new run", () => {
  expect(agentThreadSource).toContain('className="user-message-editor"');
  expect(agentThreadSource).toContain("MessageEditorContext.Provider");
  expect(agentThreadSource).toContain("isLatestUserMessage");
  expect(agentThreadSource).toContain("{isLatestUserMessage && !threadRunning ? (");
  expect(agentThreadSource).toContain("setEditor({ messageId: message.id, draft: originalText })");
  expect(agentThreadSource).toContain("sourceId: message.id");
  expect(agentThreadSource).toContain("startRun: true");
  expect(agentThreadSource).not.toContain("text === originalText.trim()");
  expect(agentThreadSource).toContain("发送");
});

it("places each run activity before its assistant answer", () => {
  const assistantRoot = agentThreadSource.indexOf(
    '<AssistantMessage.Root className="harness-assistant-message">',
  );
  const activity = agentThreadSource.indexOf("<LatestActivity />", assistantRoot);
  const content = agentThreadSource.indexOf("<AssistantMessage.Content", assistantRoot);
  expect(activity).toBeGreaterThan(assistantRoot);
  expect(content).toBeGreaterThan(activity);
  expect(agentThreadSource).toContain('className="assistant-message-controls"');
  expect(agentThreadSource).toContain('part.toolName === "harness_run_activity"');
  expect(agentThreadSource).toContain(
    "shouldKeepActivityInLatestSlot(",
  );
  expect(agentThreadSource).toContain(
    'data-activity-source="current-run"',
  );
  expect(agentThreadSource).toContain(
    "live.runId,",
  );
  expect(agentThreadSource).not.toContain("MessagesFooter: LatestActivity");
});

it("renders uploaded message files with a same-origin download link", () => {
  expect(
    inputArtifactDownloadHref("input_artifact_123", "history-index"),
  ).toBe("/api/input-artifacts/input_artifact_123/content");
  expect(agentThreadSource).toContain("HarnessMessageAttachment");
  expect(agentThreadSource).toContain("点击下载");
});

it("keeps final assistant text mounted while tool-bearing responses stream", () => {
  expect(agentThreadSource).toContain(
    "function HarnessAssistantText(_part: TextMessagePartProps)",
  );
  expect(agentThreadSource).toContain("return <MarkdownText />;");
  expect(agentThreadSource).toContain(
    "if (isIntermediateAssistantMessage(runView, messageId)) return null;",
  );
});

it("projects pre-tool assistant prose only as activity commentary", () => {
  expect(
    isIntermediateAssistantMessage(
      {
        runId: "run-1",
        phase: "running",
        startedAt: "2026-07-17T00:00:00Z",
        updatedAt: "2026-07-17T00:00:01Z",
        elapsedMs: 1000,
        summary: "正在执行",
        items: [
          {
            id: "tool-1",
            event_type: "tool.request",
            kind: "tool",
            status: "running",
            title: "调用 Glob",
            timestamp: "2026-07-17T00:00:01Z",
            sequence: 1,
            metadata: { message_id: "assistant-progress" },
          },
        ],
        tasks: [],
        tools: [],
        taskCount: 0,
        toolCount: 0,
      },
      "assistant-progress",
    ),
  ).toBe(true);
});

it("renders raw AG-UI text deltas before the durable message is finalized", () => {
  expect(agentThreadSource).toContain("MessagesFooter: LiveAssistantResponse");
  expect(agentThreadSource).toContain('className="live-assistant-response"');
  expect(agentThreadSource).toContain("TextMessagePartProvider");
  expect(agentThreadSource).toContain("hasCurrentTurnAssistantText(state.thread.messages)");
  expect(agentThreadSource).toContain("hasProjectedText ||");
});

it("suppresses the live fallback once the current turn has projected assistant text", () => {
  expect(
    hasCurrentTurnAssistantText([
      { role: "assistant", content: [{ type: "text", text: "older answer" }] },
      { role: "user", content: [{ type: "text", text: "new question" }] },
      { role: "assistant", content: [{ type: "text", text: "new answer" }] },
      { role: "tool", content: [] },
    ]),
  ).toBe(true);
  expect(
    hasCurrentTurnAssistantText([
      { role: "assistant", content: [{ type: "text", text: "older answer" }] },
      { role: "user", content: [{ type: "text", text: "new question" }] },
      { role: "tool", content: [] },
    ]),
  ).toBe(false);
});
