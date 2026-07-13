"use client";

import {
  ActionBarPrimitive,
  AttachmentPrimitive,
  AuiIf,
  ComposerPrimitive,
  MessagePrimitive,
  ThreadPrimitive,
  type ToolCallMessagePart,
} from "@assistant-ui/react";
import { ActivitySummary } from "./activity-summary";
import { ApprovalCard, type ApprovalDetails } from "./approval-card";
import { ArtifactCard, type ArtifactDetails } from "./artifact-list";
import { MarkdownText } from "./markdown-text";
import { SubagentCard } from "./subagent-card";
import { ToolCard } from "./tool-card";
import { useRunActivity } from "../lib/activity-store";

function ComposerAttachment() {
  return (
    <AttachmentPrimitive.Root className="input-file-chip">
      <span className="input-file-glyph" aria-hidden="true">↳</span>
      <span className="input-file-copy">
        <small>将挂载到 inputs/</small>
        <strong><AttachmentPrimitive.Name /></strong>
      </span>
      <AttachmentPrimitive.Remove aria-label="移除附件">×</AttachmentPrimitive.Remove>
    </AttachmentPrimitive.Root>
  );
}

function MessageAttachment() {
  return (
    <AttachmentPrimitive.Root className="message-file-chip">
      <span aria-hidden="true">FILE</span>
      <strong><AttachmentPrimitive.Name /></strong>
    </AttachmentPrimitive.Root>
  );
}

function UserMessage() {
  return (
    <MessagePrimitive.Root className="aui-message aui-user-message">
      <div className="aui-message-coordinate">YOU</div>
      <div className="aui-user-bubble">
        <MessagePrimitive.Attachments>
          {() => <MessageAttachment />}
        </MessagePrimitive.Attachments>
        <MessagePrimitive.Parts />
      </div>
      <ActionBarPrimitive.Root className="aui-message-actions">
        <ActionBarPrimitive.Copy aria-label="复制消息">复制</ActionBarPrimitive.Copy>
        <ActionBarPrimitive.Edit aria-label="编辑消息">编辑</ActionBarPrimitive.Edit>
      </ActionBarPrimitive.Root>
    </MessagePrimitive.Root>
  );
}

function toolStatus(part: ToolCallMessagePart) {
  if (part.result !== undefined) return "complete" as const;
  if (part.argsText) return "executing" as const;
  return "inProgress" as const;
}

function objectValue(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value)
    ? { ...(value as Record<string, unknown>) }
    : {};
}

function HarnessToolPart({ part }: { part: ToolCallMessagePart }) {
  const status = toolStatus(part);
  const args = objectValue(part.args);
  if (part.toolName === "Task" || part.toolName === "Agent") {
    return <SubagentCard status={status} parameters={args} result={part.result} />;
  }
  if (part.toolName === "harness_request_approval") {
    const details = args as unknown as ApprovalDetails;
    return (
      <ApprovalCard
        details={details}
        complete={part.result !== undefined}
        onDecision={async (decision) => {
          const response = await fetch(
            `/api/harness/approvals/${encodeURIComponent(details.approval_id)}`,
            {
              method: "PUT",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ decision }),
            },
          );
          if (!response.ok) throw new Error(await response.text());
        }}
      />
    );
  }
  if (part.toolName === "harness_present_artifact") {
    return <ArtifactCard details={args as unknown as ArtifactDetails} />;
  }
  return (
    <ToolCard
      name={part.toolName}
      status={status}
      args={args}
      result={part.result}
    />
  );
}

function AssistantMessage() {
  return (
    <MessagePrimitive.Root className="aui-message aui-assistant-message">
      <div className="aui-message-coordinate">AGENT</div>
      <div className="aui-assistant-body">
        <MessagePrimitive.Parts>
          {({ part }) => {
            if (part.type === "text") return <MarkdownText />;
            if (part.type === "reasoning") {
              return (
                <details className="reasoning-card" open>
                  <summary><span aria-hidden="true">◇</span> 思考过程</summary>
                  <div>{part.text}</div>
                </details>
              );
            }
            if (part.type === "tool-call") {
              return <HarnessToolPart part={part} />;
            }
            return null;
          }}
        </MessagePrimitive.Parts>
        <AuiIf condition={(state) => state.message.status?.type === "incomplete"}>
          <div className="aui-message-error">本次运行未完整结束，请查看运行详情。</div>
        </AuiIf>
      </div>
      <ActionBarPrimitive.Root className="aui-message-actions">
        <ActionBarPrimitive.Copy aria-label="复制回答">复制</ActionBarPrimitive.Copy>
        <ActionBarPrimitive.Reload aria-label="重新运行">重新运行</ActionBarPrimitive.Reload>
      </ActionBarPrimitive.Root>
    </MessagePrimitive.Root>
  );
}

function LatestActivity() {
  const activity = useRunActivity();
  return activity ? (
    <div className="latest-activity"><ActivitySummary activity={activity} /></div>
  ) : null;
}

function Composer() {
  return (
    <ComposerPrimitive.AttachmentDropzone className="composer-dropzone">
      <ComposerPrimitive.Root className="aui-composer">
        <ComposerPrimitive.Attachments>
          {() => <ComposerAttachment />}
        </ComposerPrimitive.Attachments>
        <ComposerPrimitive.Input
          className="aui-composer-input"
          placeholder="描述任务，或附加文件让 Agent 读取…"
          rows={1}
          aria-label="给 Agent 的任务"
        />
        <div className="aui-composer-toolbar">
          <ComposerPrimitive.AddAttachment
            className="composer-tool-button"
            aria-label="添加本地文件"
            multiple
          >
            ＋ 文件
          </ComposerPrimitive.AddAttachment>
          <span>文件会上传并挂载到本次运行的 inputs/</span>
          <AuiIf condition={(state) => !state.thread.isRunning}>
            <ComposerPrimitive.Send className="composer-send" aria-label="发送任务">
              运行 ↗
            </ComposerPrimitive.Send>
          </AuiIf>
          <AuiIf condition={(state) => state.thread.isRunning}>
            <ComposerPrimitive.Cancel className="composer-cancel" aria-label="停止运行">
              停止
            </ComposerPrimitive.Cancel>
          </AuiIf>
        </div>
      </ComposerPrimitive.Root>
    </ComposerPrimitive.AttachmentDropzone>
  );
}

function Welcome() {
  const prompts = [
    "分析这个仓库的架构风险，并给出可执行的重构顺序",
    "读取我附加的文档，提取关键事实并标出证据位置",
    "把复杂任务拆给子 Agent，并汇总工具调用和最终结论",
  ];
  return (
    <section className="aui-welcome">
      <div className="welcome-signal" aria-hidden="true"><span>H</span></div>
      <p className="eyebrow">Workspace ready</p>
      <h2>让 Agent 真正执行，而不只是聊天</h2>
      <p>上传输入、观察思考与工具过程，并在运行详情中核对每一个事件。</p>
      <div className="welcome-prompts">
        {prompts.map((prompt) => (
          <ThreadPrimitive.Suggestion key={prompt} prompt={prompt} send>
            <span>{prompt}</span><b aria-hidden="true">↗</b>
          </ThreadPrimitive.Suggestion>
        ))}
      </div>
    </section>
  );
}

export function AgentThread() {
  return (
    <ThreadPrimitive.Root className="aui-thread">
      <ThreadPrimitive.Viewport className="aui-thread-viewport" autoScroll>
        <AuiIf condition={(state) => state.thread.isEmpty}><Welcome /></AuiIf>
        <div className="aui-message-list">
          <ThreadPrimitive.Messages>
            {({ message }) =>
              message.role === "user" ? <UserMessage /> : <AssistantMessage />
            }
          </ThreadPrimitive.Messages>
          <LatestActivity />
        </div>
        <ThreadPrimitive.ViewportFooter className="aui-viewport-footer">
          <ThreadPrimitive.ScrollToBottom className="scroll-to-bottom" aria-label="滚动到底部">
            ↓
          </ThreadPrimitive.ScrollToBottom>
          <Composer />
          <p className="runtime-disclaimer">Claude Agent SDK · new-api gateway · 输出可能需要人工核验</p>
        </ThreadPrimitive.ViewportFooter>
      </ThreadPrimitive.Viewport>
    </ThreadPrimitive.Root>
  );
}
