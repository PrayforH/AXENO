"use client";

import {
  AssistantRuntimeProvider,
  WebSpeechSynthesisAdapter,
} from "@assistant-ui/react";
import { useAgUiRuntime } from "@assistant-ui/react-ag-ui";
import type { ReactNode } from "react";
import { useEffect, useMemo } from "react";
import { activityStore, useRunViewModel } from "../lib/activity-store";
import { HarnessHttpAgent } from "../lib/harness-agent";
import { createInputAttachmentAdapter } from "../lib/input-attachment-adapter";
import { liveResponseStore } from "../lib/live-response-store";
import { uploadFeedbackStore } from "../lib/upload-feedback-store";
import { createThreadHistoryAdapter } from "../lib/task-history";

export function AssistantRuntimeShell({
  threadId,
  agentName,
  agentVersion,
  children,
}: {
  threadId: string;
  agentName: string;
  agentVersion: string;
  children: ReactNode;
}) {
  const runView = useRunViewModel();
  const agent = useMemo(() => {
    const query = new URLSearchParams({
      agent_name: agentName,
      agent_version: agentVersion,
    });
    const next = new HarnessHttpAgent({ url: `/api/agui?${query.toString()}` });
    next.threadId = threadId;
    return next;
  }, [agentName, agentVersion, threadId]);
  const attachments = useMemo(() => createInputAttachmentAdapter(), []);
  const speech = useMemo(() => new WebSpeechSynthesisAdapter(), []);
  const history = useMemo(() => createThreadHistoryAdapter(threadId), [threadId]);
  useEffect(() => {
    activityStore.clear();
    liveResponseStore.clear();
    uploadFeedbackStore.clear();
  }, [threadId]);
  const runtime = useAgUiRuntime({
    agent,
    showThinking: true,
    adapters: { attachments, speech, history },
    onCancel: () => agent.cancelActiveRun(),
    onError: (error) => console.error("[Harness Console]", error),
  });

  return (
    <AssistantRuntimeProvider runtime={runtime}>
      <div
        className="assistant-runtime-shell"
        data-run-phase={runView?.phase ?? "idle"}
      >
        {children}
      </div>
    </AssistantRuntimeProvider>
  );
}
