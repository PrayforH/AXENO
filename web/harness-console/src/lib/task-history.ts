import {
  ExportedMessageRepository,
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

export function createThreadHistoryAdapter(threadId: string): ThreadHistoryAdapter {
  return {
    async load() {
      const response = requireAuthenticatedResponse(
        await fetch(
          `/api/agui/threads/${encodeURIComponent(threadId)}/history`,
          { cache: "no-store" },
        ),
      );
      if (response.status === 404) {
        return ExportedMessageRepository.fromArray([]);
      }
      if (!response.ok) {
        throw new Error((await response.text()) || `HTTP ${response.status}`);
      }
      const history = (await response.json()) as ThreadHistoryResponse;
      const restoredActivity = latestHistoryRunActivity(history.messages);
      if (restoredActivity) activityStore.publish(restoredActivity, threadId);
      return ExportedMessageRepository.fromArray(
        fromAgUiMessages(history.messages, { showThinking: true }),
      );
    },
    async append() {
      // Harness run events are the durable source of truth. The history endpoint
      // reconstructs messages from them, so no second client-side write is needed.
    },
  };
}
