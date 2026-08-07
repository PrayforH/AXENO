import {
  ExportedMessageRepository,
  type ChatModelRunOptions,
  type ChatModelRunResult,
  type ThreadHistoryAdapter,
} from "@assistant-ui/core";
import { fromAgUiMessages } from "@assistant-ui/react-ag-ui";
import type { ApprovalDetails } from "../components/approval-card";
import { latestHistoryRunActivity } from "./activity-schema";
import { activityStore } from "./activity-store";
import { requireAuthenticatedResponse } from "./client-auth";

export interface TaskSummary {
  thread_id: string;
  session_id: string;
  title: string;
  agent_name: string;
  agent_version: string;
  agent_owner_user_id: string;
  space_id?: string | null;
  status: string;
  run_id?: string;
  created_at: string;
  updated_at: string;
  pending_approval?: (ApprovalDetails & { status: string }) | null;
}

interface ThreadHistoryResponse {
  thread_id: string;
  status: string;
  run_id?: string | null;
  messages: Array<{
    id: string;
    role: string;
    content: string;
    toolCalls?: unknown[];
    tool_calls?: unknown[];
    toolCallId?: string;
    tool_call_id?: string;
  }>;
}

const activeStatuses = new Set([
  "queued",
  "provisioning",
  "running",
  "waiting_approval",
  "cancelling",
]);

function resumedStatus(status: string): NonNullable<ChatModelRunResult["status"]> {
  if (activeStatuses.has(status)) return { type: "running" };
  if (status === "cancelled") return { type: "incomplete", reason: "cancelled" };
  if (["failed", "rejected", "timed_out"].includes(status)) {
    return {
      type: "incomplete",
      reason: "error",
      error: `任务已${status === "timed_out" ? "超时" : "失败"}`,
    };
  }
  return { type: "complete", reason: "unknown" };
}

function waitForHistoryPoll(signal: AbortSignal, milliseconds = 500) {
  return new Promise<void>((resolve, reject) => {
    if (signal.aborted) {
      reject(signal.reason);
      return;
    }
    const timer = globalThis.setTimeout(done, milliseconds);
    function done() {
      signal.removeEventListener("abort", cancelled);
      resolve();
    }
    function cancelled() {
      globalThis.clearTimeout(timer);
      reject(signal.reason);
    }
    signal.addEventListener("abort", cancelled, { once: true });
  });
}

function historyUrl(threadId: string) {
  return `/api/agui/threads/${encodeURIComponent(threadId)}/history`;
}

async function loadThreadHistory(
  threadId: string,
  signal?: AbortSignal,
): Promise<ThreadHistoryResponse | null> {
  const response = requireAuthenticatedResponse(
    await fetch(historyUrl(threadId), { cache: "no-store", signal }),
  );
  if (response.status === 404) return null;
  if (!response.ok) {
    throw new Error((await response.text()) || `HTTP ${response.status}`);
  }
  return response.json() as Promise<ThreadHistoryResponse>;
}

function publishHistoryActivity(history: ThreadHistoryResponse, threadId: string) {
  const restoredActivity = latestHistoryRunActivity(history.messages);
  if (restoredActivity) activityStore.publish(restoredActivity, threadId);
}

async function json<T>(url: string): Promise<T> {
  const response = requireAuthenticatedResponse(
    await fetch(url, { cache: "no-store" }),
  );
  if (!response.ok) {
    throw new Error((await response.text()) || `HTTP ${response.status}`);
  }
  return response.json() as Promise<T>;
}

export function loadTasks(archived = false): Promise<TaskSummary[]> {
  return json<TaskSummary[]>(`/api/agui/threads?archived=${archived}`);
}

export async function setTaskArchived(
  threadId: string,
  archived: boolean,
): Promise<void> {
  const response = requireAuthenticatedResponse(
    await fetch(`/api/agui/threads/${encodeURIComponent(threadId)}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ archived }),
    }),
  );
  if (!response.ok) {
    throw new Error((await response.text()) || `HTTP ${response.status}`);
  }
}

export function createThreadHistoryAdapter(
  threadId: string,
  options: { onActiveRun?: (serverRunId: string) => void } = {},
): ThreadHistoryAdapter & { dispose(): void } {
  const disposal = new AbortController();
  return {
    async load() {
      const history = await loadThreadHistory(threadId, disposal.signal);
      if (!history) {
        return ExportedMessageRepository.fromArray([]);
      }
      publishHistoryActivity(history, threadId);
      const repository = ExportedMessageRepository.fromArray(
        fromAgUiMessages(history.messages, { showThinking: true }),
      );
      if (!history.run_id || !activeStatuses.has(history.status)) {
        return repository;
      }

      options.onActiveRun?.(history.run_id);
      const activeAssistantId = `assistant-${history.run_id}`;
      const activeAssistant = repository.messages.find(
        (item) => item.message.id === activeAssistantId,
      );
      return {
        ...repository,
        // Resume replaces the partial assistant snapshot. Rewind to its
        // parent so assistant-ui does not append a duplicate response.
        headId: activeAssistant?.parentId ?? repository.messages.at(-1)?.message.id ?? null,
        unstable_resume: true,
      };
    },
    async *resume(resumeOptions: ChatModelRunOptions) {
      const signal = AbortSignal.any([
        disposal.signal,
        resumeOptions.abortSignal,
      ]);
      let lastSnapshot = "";
      while (!signal.aborted) {
        let history: ThreadHistoryResponse | null;
        try {
          history = await loadThreadHistory(threadId, signal);
        } catch (error) {
          if (signal.aborted) return;
          throw error;
        }
        if (!history) return;
        publishHistoryActivity(history, threadId);
        if (history.run_id && activeStatuses.has(history.status)) {
          options.onActiveRun?.(history.run_id);
        }

        const repository = ExportedMessageRepository.fromArray(
          fromAgUiMessages(history.messages, { showThinking: true }),
        );
        const assistant = history.run_id
          ? repository.messages.find(
              (item) => item.message.id === `assistant-${history.run_id}`,
            )?.message
          : undefined;
        const status = resumedStatus(history.status);
        const update: ChatModelRunResult = {
          ...(assistant?.role === "assistant"
            ? { content: assistant.content, metadata: assistant.metadata }
            : {}),
          status,
        };
        const snapshot = JSON.stringify(update);
        if (snapshot !== lastSnapshot) {
          lastSnapshot = snapshot;
          yield update;
        }
        if (!activeStatuses.has(history.status)) return;
        try {
          await waitForHistoryPoll(signal);
        } catch {
          if (signal.aborted) return;
          throw new Error("恢复任务输出时轮询中断");
        }
      }
    },
    async append() {
      // Harness run events are the durable source of truth. The history endpoint
      // reconstructs messages from them, so no second client-side write is needed.
    },
    dispose() {
      disposal.abort(new DOMException("Task view unmounted", "AbortError"));
    },
  };
}
