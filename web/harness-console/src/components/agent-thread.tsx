"use client";

import {
  ActionBarPrimitive,
  AttachmentPrimitive,
  AuiIf,
  MessagePrimitive,
  useAttachment,
  useAui,
  useAuiState,
  useThreadRuntime,
  type ReasoningMessagePartComponent,
  type TextMessagePartProps,
  type ToolCallMessagePartProps,
} from "@assistant-ui/react";
import {
  createContext,
  type FormEvent,
  useContext,
  useState,
} from "react";
import {
  AssistantActionBar,
  AssistantMessage,
  BranchPicker,
  Composer,
  Thread,
  ThreadWelcome,
  UserMessage,
} from "@assistant-ui/react-ui";
import { ActivitySummary } from "./activity-summary";
import { ApprovalCard, type ApprovalDetails } from "./approval-card";
import { ArtifactCard, type ArtifactDetails } from "./artifact-list";
import { MarkdownText } from "./markdown-text";
import { SubagentCard } from "./subagent-card";
import { ToolCard } from "./tool-card";
import { useRunActivity, useRunViewModel } from "../lib/activity-store";
import { selectComposerDisabled } from "../lib/run-view-model";
import { runActivitySchema } from "../lib/activity-schema";
import { requireAuthenticatedResponse } from "../lib/client-auth";
import { useRunStream } from "../lib/run-stream-store";
import {
  type UploadFeedback,
  uploadFeedbackStore,
  useUploadFeedback,
} from "../lib/upload-feedback-store";

export function UploadFeedbackContent({
  items,
  onDismiss,
}: {
  items: readonly UploadFeedback[];
  onDismiss: (key: string) => void;
}) {
  if (items.length === 0) return null;
  return (
    <div className="upload-feedback" aria-live="polite" aria-label="附件上传状态">
      {items.map((item) => (
        <div key={item.key} className={`upload-feedback-item ${item.status}`}>
          <span aria-hidden="true">
            {item.status === "uploading" ? "↻" : item.status === "ready" ? "✓" : "!"}
          </span>
          <span>
            <strong>{item.fileName}</strong>
            {item.status === "uploading"
              ? " 正在上传"
              : item.status === "ready"
                ? " 已就绪"
                : ` 上传失败：${item.message ?? "未知错误"}`}
          </span>
          {item.status === "error" ? (
            <button
              type="button"
              onClick={() => onDismiss(item.key)}
              aria-label={`关闭 ${item.fileName} 上传错误`}
            >
              ×
            </button>
          ) : null}
        </div>
      ))}
    </div>
  );
}

function UploadFeedbackNotice() {
  const items = useUploadFeedback();
  return <UploadFeedbackContent items={items} onDismiss={uploadFeedbackStore.dismiss} />;
}

function HarnessComposer() {
  const runView = useRunViewModel();
  const runLocked = selectComposerDisabled(runView);
  const composerHint = runLocked
    ? runView?.phase === "waiting_approval"
      ? "处理审批后，Agent 会从当前步骤继续"
      : "Agent 正在执行，可随时停止"
    : "Enter 发送 · Shift + Enter 换行";
  return (
    <div
      className="harness-composer-shell"
      data-run-phase={runView?.phase ?? "idle"}
      data-run-locked={runLocked ? "true" : "false"}
      aria-busy={runLocked}
    >
      <UploadFeedbackNotice />
      <Composer />
      <div className="composer-meta" aria-live="polite">
        <span className="sandbox-indicator"><i aria-hidden="true" />隔离工作区</span>
        <span>{composerHint}</span>
      </div>
    </div>
  );
}

const welcomeTasks = [
  {
    code: "PLAN",
    title: "分析与规划",
    description: "梳理复杂问题，输出有优先级的行动方案",
    prompt: "分析这个仓库的架构风险，并给出可执行、带优先级的重构顺序",
  },
  {
    code: "READ",
    title: "阅读与整理",
    description: "读取附件，提取事实、证据和结构化摘要",
    prompt: "读取我附加的文档，提取关键事实并标出证据位置",
  },
  {
    code: "ACT",
    title: "执行与协作",
    description: "调用工具或子 Agent，完成多步骤任务",
    prompt: "把复杂任务拆给子 Agent，并汇总工具调用和最终结论",
  },
] as const;

export function UserTaskWelcome() {
  return (
    <ThreadWelcome.Root className="user-task-welcome">
      <ThreadWelcome.Center className="user-task-hero">
        <div className="user-task-intro">
          <p className="user-task-kicker"><span aria-hidden="true" />开始一项任务</p>
          <h2>把目标交给 Agent</h2>
          <p>
            描述期望结果，或附上资料。Agent 会规划步骤、调用工具，并在关键操作前请求确认。
          </p>
        </div>
      </ThreadWelcome.Center>

      <div className="user-task-grid" aria-label="推荐任务">
        {welcomeTasks.map((task) => (
          <ThreadWelcome.Suggestion
            key={task.code}
            suggestion={{
              prompt: task.prompt,
              text: (
                <span className="user-task-card-copy">
                  <small>{task.code}</small>
                  <strong>{task.title}</strong>
                  <span>{task.description}</span>
                </span>
              ),
            }}
          />
        ))}
      </div>

      <p className="user-task-trust">
        <span aria-hidden="true" />
        工具在隔离工作区运行 · 支持人工审批 · 产物可直接下载
      </p>
    </ThreadWelcome.Root>
  );
}

function toolStatus(part: ToolCallMessagePartProps) {
  if (part.result !== undefined) return "complete" as const;
  if (part.argsText) return "executing" as const;
  return "inProgress" as const;
}

function objectValue(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value)
    ? { ...(value as Record<string, unknown>) }
    : {};
}

function useAssistantResponseStarted() {
  return useAuiState((state) =>
    state.message.content.some(
      (part) => part.type === "text" && part.text.trim().length > 0,
    ),
  );
}

export function hasProjectedTool(
  view: ReturnType<typeof useRunViewModel>,
  toolCallId: string | undefined,
) {
  return Boolean(
    toolCallId && view?.tools.some((tool) => tool.id === toolCallId),
  );
}

export function shouldKeepActivityInLatestSlot(
  activityRunId: string,
  viewRunId: string | undefined,
  liveRunId: string | undefined,
) {
  return (
    viewRunId === activityRunId &&
    (liveRunId === undefined || liveRunId === activityRunId)
  );
}

function HarnessToolPart(part: ToolCallMessagePartProps) {
  const status = toolStatus(part);
  const args = objectValue(part.args);
  const runView = useRunViewModel();
  const stream = useRunStream();
  if (part.toolName === "harness_run_activity") {
    const parsed = runActivitySchema.safeParse(args.activity);
    if (
      !parsed.success ||
      shouldKeepActivityInLatestSlot(
        parsed.data.run_id,
        runView?.runId,
        stream.runId,
      )
    ) {
      return null;
    }
    return (
      <div className="turn-activity-summary">
        <ActivitySummary activity={parsed.data} responseStarted />
      </div>
    );
  }
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
          const response = requireAuthenticatedResponse(
            await fetch(
              `/api/harness/approvals/${encodeURIComponent(details.approval_id)}`,
              {
                method: "PUT",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ decision }),
              },
            ),
          );
          if (!response.ok) throw new Error(await response.text());
        }}
      />
    );
  }
  if (part.toolName === "harness_present_artifact") {
    return <ArtifactCard details={args as unknown as ArtifactDetails} />;
  }
  if (hasProjectedTool(runView, part.toolCallId)) {
    return null;
  }
  return (
    <ToolCard
      toolCallId={part.toolCallId}
      name={part.toolName}
      status={status}
      args={args}
      result={part.result}
      isError={part.isError}
    />
  );
}

const ReasoningPart: ReasoningMessagePartComponent = ({ text, status }) => (
  <details className="reasoning-card" open={status.type === "running"}>
    <summary>
      <span className="reasoning-mark" aria-hidden="true" />
      <span>{status.type === "running" ? "正在思考" : "已思考"}</span>
      <small>{status.type === "running" ? "进行中" : "展开查看"}</small>
    </summary>
    <div>{text}</div>
  </details>
);

type AssistantPartLike = {
  type?: string;
};

export function isIntermediateAssistantTextPart(
  parts: readonly AssistantPartLike[],
  partIndex: number,
) {
  return (
    partIndex >= 0 &&
    parts[partIndex]?.type === "text" &&
    parts.slice(partIndex + 1).some((part) => part.type === "tool-call")
  );
}

function HarnessAssistantText(part: TextMessagePartProps) {
  const aui = useAui();
  const parts = useAuiState((state) => state.message.content);
  const partIndex =
    aui.part.source === "message" && aui.part.query.type === "index"
      ? aui.part.query.index
      : -1;
  if (isIntermediateAssistantTextPart(parts, partIndex)) return null;
  return (
    <div
      className="assistant-answer"
      data-streaming={part.status.type === "running" ? "true" : "false"}
      aria-busy={part.status.type === "running"}
    >
      <MarkdownText />
    </div>
  );
}

function HarnessAssistantMessage() {
  return (
    <AssistantMessage.Root className="harness-assistant-message">
      <AuiIf condition={(state) => state.message.isLast}>
        <LatestActivity />
      </AuiIf>
      <AssistantMessage.Content
        components={{
          Text: HarnessAssistantText,
          Reasoning: ReasoningPart,
        }}
      />
      <AuiIf condition={(state) => state.message.status?.type === "incomplete"}>
        <div className="aui-message-error">本次运行未完整结束，可打开“运行详情”查看原因。</div>
      </AuiIf>
      <div className="assistant-message-controls">
        <BranchPicker />
        <AssistantActionBar />
      </div>
    </AssistantMessage.Root>
  );
}

function EditMessageIcon() {
  return (
    <svg viewBox="0 0 20 20" aria-hidden="true">
      <path d="M4 14.8 4.7 12 13 3.7a1.4 1.4 0 0 1 2 0l1.3 1.3a1.4 1.4 0 0 1 0 2L8 15.3l-2.8.7Z" />
      <path d="m12 4.7 3.3 3.3" />
    </svg>
  );
}

function CopyMessageIcon() {
  return (
    <svg viewBox="0 0 20 20" aria-hidden="true">
      <rect x="6.5" y="6.5" width="9" height="9" rx="1.5" />
      <path d="M13.5 6.5v-2a1.5 1.5 0 0 0-1.5-1.5H4.5A1.5 1.5 0 0 0 3 4.5V12A1.5 1.5 0 0 0 4.5 13h2" />
    </svg>
  );
}

function AttachmentFileIcon() {
  return (
    <svg viewBox="0 0 20 20" aria-hidden="true">
      <path d="M5.5 2.8h5.8l3.2 3.3v11.1H5.5Z" />
      <path d="M11.2 2.8v3.5h3.3" />
      <path d="M7.8 10h4.4M7.8 13h4.4" />
    </svg>
  );
}

export function inputArtifactDownloadHref(
  data: string | undefined,
  attachmentId: string,
) {
  const artifactId = data?.startsWith("input_artifact_")
    ? data
    : attachmentId.startsWith("input_artifact_")
      ? attachmentId
      : undefined;
  return artifactId
    ? `/api/input-artifacts/${encodeURIComponent(artifactId)}/content`
    : undefined;
}

function HarnessMessageAttachment() {
  const attachment = useAttachment((state) => state);
  const filePart = attachment.content?.find((part) => part.type === "file");
  const data = filePart?.type === "file" ? filePart.data : undefined;
  const href = inputArtifactDownloadHref(data, attachment.id);
  const extension = attachment.name.split(".").at(-1)?.toUpperCase() || "文件";
  const content = (
    <>
      <span className="message-attachment-icon"><AttachmentFileIcon /></span>
      <span className="message-attachment-copy">
        <strong>{attachment.name}</strong>
        <small>{extension} 文件{href ? " · 点击下载" : ""}</small>
      </span>
    </>
  );
  return (
    <AttachmentPrimitive.Root className="message-attachment-card">
      {href ? (
        <a href={href} download={attachment.name} title={`下载 ${attachment.name}`}>
          {content}
        </a>
      ) : (
        <span className="message-attachment-static">{content}</span>
      )}
    </AttachmentPrimitive.Root>
  );
}

type MessageEditorState = {
  messageId: string;
  draft: string;
} | null;

type MessageEditorController = {
  editor: MessageEditorState;
  setEditor: (editor: MessageEditorState) => void;
};

const MessageEditorContext = createContext<MessageEditorController | null>(null);

function useMessageEditor() {
  const controller = useContext(MessageEditorContext);
  if (!controller) throw new Error("Message editor must be rendered inside AgentThread");
  return controller;
}

function HarnessUserMessage() {
  const message = useAuiState((state) => state.message);
  const threadRunning = useAuiState((state) => state.thread.isRunning);
  const isLatestUserMessage = useAuiState((state) => {
    for (let index = state.thread.messages.length - 1; index >= 0; index -= 1) {
      const candidate = state.thread.messages[index];
      if (candidate?.role === "user") return candidate.id === state.message.id;
    }
    return false;
  });
  const thread = useThreadRuntime();
  const { editor, setEditor } = useMessageEditor();
  const originalText = message.content
    .filter((part) => part.type === "text")
    .map((part) => part.text)
    .join("\n");
  const editing = editor?.messageId === message.id;
  const draft = editing ? editor.draft : originalText;

  function beginEdit() {
    setEditor({ messageId: message.id, draft: originalText });
  }

  function submitEdit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const text = draft.trim();
    if (!text || threadRunning || !isLatestUserMessage) return;
    const parentId =
      message.index > 0 ? thread.getState().messages[message.index - 1]?.id ?? null : null;
    thread.append({
      parentId,
      sourceId: message.id,
      role: "user",
      content: [{ type: "text", text }],
      attachments: message.attachments,
      startRun: true,
    });
    setEditor(null);
  }

  return (
      <UserMessage.Root className="harness-user-message">
      <UserMessage.Attachments
        components={{ Attachment: HarnessMessageAttachment }}
      />
      <MessagePrimitive.If hasContent>
        {editing ? (
          <form className="user-message-editor" onSubmit={submitEdit}>
            <textarea
              className="user-message-editor-input"
              aria-label="编辑用户输入"
              value={draft}
              onChange={(event) => {
                setEditor({ messageId: message.id, draft: event.target.value });
              }}
              onKeyDown={(event) => {
                if (event.key === "Escape") setEditor(null);
              }}
              autoFocus
              rows={Math.min(8, Math.max(2, draft.split("\n").length))}
            />
            <div className="user-message-editor-actions">
              <button type="button" onClick={() => setEditor(null)}>取消</button>
              <button type="submit" disabled={!draft.trim() || threadRunning}>
                发送
              </button>
            </div>
          </form>
        ) : (
          <>
            <UserMessage.Content />
            <ActionBarPrimitive.Root
              className="harness-user-action-bar"
              autohide="never"
            >
              <ActionBarPrimitive.Copy
                className="user-message-action"
                aria-label="复制消息"
                title="复制消息"
                copiedDuration={1800}
              >
                <CopyMessageIcon />
              </ActionBarPrimitive.Copy>
              {isLatestUserMessage && !threadRunning ? (
                <button
                  className="user-message-action"
                  type="button"
                  aria-label="编辑消息"
                  title="编辑消息"
                  onClick={beginEdit}
                >
                  <EditMessageIcon />
                </button>
              ) : null}
            </ActionBarPrimitive.Root>
          </>
        )}
      </MessagePrimitive.If>
      <BranchPicker />
    </UserMessage.Root>
  );
}

function LatestActivity() {
  const activity = useRunActivity();
  const runView = useRunViewModel();
  const stream = useRunStream();
  const finalResponseStarted = useAssistantResponseStarted();
  if (
    !activity ||
    !runView ||
    !shouldKeepActivityInLatestSlot(
      activity.run_id,
      runView.runId,
      stream.runId,
    )
  ) {
    return null;
  }
  return (
    <div
      className={`latest-activity ${runView.phase}`}
      data-activity-source="current-run"
    >
      <ActivitySummary
        activity={activity}
        responseStarted={finalResponseStarted}
      />
    </div>
  );
}

export function AgentThread() {
  const [editor, setEditor] = useState<MessageEditorState>(null);
  return (
    <MessageEditorContext.Provider value={{ editor, setEditor }}>
      <Thread
      assistantMessage={{
        allowCopy: true,
        allowReload: true,
        allowSpeak: true,
        allowFeedbackPositive: true,
        allowFeedbackNegative: true,
        components: { ToolFallback: HarnessToolPart },
      }}
      userMessage={{ allowEdit: true }}
      branchPicker={{ allowBranchPicker: true }}
      composer={{ allowAttachments: true }}
      components={{
        AssistantMessage: HarnessAssistantMessage,
        UserMessage: HarnessUserMessage,
        Composer: HarnessComposer,
        ThreadWelcome: UserTaskWelcome,
      }}
      strings={{
        thread: { scrollToBottom: { tooltip: "滚动到底部" } },
        userMessage: { edit: { tooltip: "编辑消息" } },
        assistantMessage: {
          reload: { tooltip: "重新运行" },
          copy: { tooltip: "复制回答" },
          speak: { tooltip: "朗读回答", stop: { tooltip: "停止朗读" } },
          feedback: {
            positive: { tooltip: "回答有帮助" },
            negative: { tooltip: "回答需改进" },
          },
        },
        branchPicker: {
          previous: { tooltip: "上一个分支" },
          next: { tooltip: "下一个分支" },
        },
        composer: {
          send: { tooltip: "发送任务" },
          cancel: { tooltip: "停止运行" },
          addAttachment: { tooltip: "添加本地文件" },
          removeAttachment: { tooltip: "移除附件" },
          input: { placeholder: "描述任务，或附加文件…" },
        },
        editComposer: { send: { label: "更新" }, cancel: { label: "取消" } },
      }}
      />
    </MessageEditorContext.Provider>
  );
}
