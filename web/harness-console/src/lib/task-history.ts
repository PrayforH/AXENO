import {
  ExportedMessageRepository,
  type ThreadHistoryAdapter,
} from "@assistant-ui/core";
import { fromAgUiMessages } from "@assistant-ui/react-ag-ui";
import type { ApprovalDetails } from "../components/approval-card";
import { latestHistoryRunActivity } from "./activity-schema";
import { activityStore } from "./activity-store";

export interface TaskSummary {
  thread_id: string;
  session_id: string;
  title: string;
  agent_name: string;
  agent_version: string;
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
  const response = await fetch(url, { cache: "no-store" });
  if (!response.ok) {
    throw new Error((await response.text()) || `HTTP ${response.status}`);
  }
  return response.json() as Promise<T>;
}

export function loadTasks(): Promise<TaskSummary[]> {
  return json<TaskSummary[]>("/api/agui/threads");
}

export function createThreadHistoryAdapter(threadId: string): ThreadHistoryAdapter {
  return {
    async load() {
      const response = await fetch(
        `/api/agui/threads/${encodeURIComponent(threadId)}/history`,
        { cache: "no-store" },
      );
      if (response.status === 404) {
        return ExportedMessageRepository.fromArray([]);
      }
      if (!response.ok) {
        throw new Error((await response.text()) || `HTTP ${response.status}`);
      }
      const history = (await response.json()) as ThreadHistoryResponse;
      const restoredActivity = latestHistoryRunActivity(history.messages);
      if (restoredActivity) activityStore.publish(restoredActivity);
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
