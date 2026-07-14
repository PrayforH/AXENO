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
import { uploadFeedbackStore } from "../lib/upload-feedback-store";

export function AssistantRuntimeShell({
  threadId,
  children,
}: {
  threadId: string;
  children: ReactNode;
}) {
  const runView = useRunViewModel();
  const agent = useMemo(() => {
    const next = new HarnessHttpAgent({ url: "/api/agui" });
    next.threadId = threadId;
    return next;
  }, [threadId]);
  const attachments = useMemo(() => createInputAttachmentAdapter(), []);
  const speech = useMemo(() => new WebSpeechSynthesisAdapter(), []);
  useEffect(() => {
    activityStore.clear();
    uploadFeedbackStore.clear();
  }, [threadId]);
  const runtime = useAgUiRuntime({
    agent,
    showThinking: true,
    adapters: { attachments, speech },
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
