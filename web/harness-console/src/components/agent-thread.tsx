"use client";

import {
  AuiIf,
  MessagePrimitive,
  type ReasoningMessagePartComponent,
  type ToolCallMessagePartProps,
} from "@assistant-ui/react";
import {
  AssistantActionBar,
  AssistantMessage,
  BranchPicker,
  Composer,
  Thread,
  ThreadWelcome,
} from "@assistant-ui/react-ui";
import { ActivitySummary } from "./activity-summary";
import { ApprovalCard, type ApprovalDetails } from "./approval-card";
import { ArtifactCard, type ArtifactDetails } from "./artifact-list";
import { MarkdownText } from "./markdown-text";
import { SubagentCard } from "./subagent-card";
import { ToolCard } from "./tool-card";
import { useRunActivity, useRunViewModel } from "../lib/activity-store";
import { selectComposerDisabled } from "../lib/run-view-model";
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
  return (
    <div
      className="harness-composer-shell"
      data-run-phase={runView?.phase ?? "idle"}
      data-run-locked={runLocked ? "true" : "false"}
      aria-busy={runLocked}
    >
      <UploadFeedbackNotice />
      <Composer />
      <p className="runtime-disclaimer">
        文件在隔离工作区中处理 · 关键操作会先请求确认
      </p>
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
        <ThreadWelcome.Avatar />
        <div className="user-task-intro">
          <p className="user-task-kicker">开始一项任务</p>
          <h2>今天想让 Agent 完成什么？</h2>
          <p>
            描述目标或附加资料。Agent 可以分析、整理和执行复杂任务，并持续汇报进展。
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
        <span aria-hidden="true">✓</span>
        文件在隔离工作区中处理，关键操作会先请求确认
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

function HarnessToolPart(part: ToolCallMessagePartProps) {
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

const ReasoningPart: ReasoningMessagePartComponent = ({ text, status }) => (
  <details className="reasoning-card" open={status.type === "running"}>
    <summary>
      <span aria-hidden="true">◇</span> 思考过程
      <span>{status.type === "running" ? "进行中" : "已完成"}</span>
    </summary>
    <div>{text}</div>
  </details>
);

function HarnessAssistantMessage() {
  return (
    <AssistantMessage.Root>
      <AssistantMessage.Avatar />
      <AssistantMessage.Content
        components={{
          Text: MarkdownText,
          Reasoning: ReasoningPart,
        }}
      />
      <AuiIf condition={(state) => state.message.status?.type === "incomplete"}>
        <div className="aui-message-error">本次运行未完整结束，请查看运行详情。</div>
      </AuiIf>
      <BranchPicker />
      <AssistantActionBar />
    </AssistantMessage.Root>
  );
}

function LatestActivity() {
  const activity = useRunActivity();
  const runView = useRunViewModel();
  if (!activity || !runView) return null;
  return (
    <div className={`latest-activity ${runView.phase}`}>
      <ActivitySummary activity={activity} />
    </div>
  );
}

export function AgentThread() {
  return (
    <Thread
      assistantAvatar={{ fallback: "H" }}
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
        Composer: HarnessComposer,
        ThreadWelcome: UserTaskWelcome,
        MessagesFooter: LatestActivity,
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
          input: { placeholder: "描述你希望完成的任务，可附加文件或资料…" },
        },
        editComposer: { send: { label: "更新" }, cancel: { label: "取消" } },
      }}
    />
  );
}
