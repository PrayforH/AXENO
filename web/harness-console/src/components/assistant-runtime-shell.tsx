"use client";

import { AssistantRuntimeProvider } from "@assistant-ui/react";
import { useAgUiRuntime } from "@assistant-ui/react-ag-ui";
import type { ReactNode } from "react";
import { useEffect, useMemo } from "react";
import { activityStore } from "../lib/activity-store";
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
  const agent = useMemo(() => {
    const next = new HarnessHttpAgent({ url: "/api/agui" });
    next.threadId = threadId;
    return next;
  }, [threadId]);
  const attachments = useMemo(() => createInputAttachmentAdapter(), []);
  useEffect(() => {
    activityStore.clear();
    uploadFeedbackStore.clear();
  }, [threadId]);
  const runtime = useAgUiRuntime({
    agent,
    showThinking: true,
    adapters: { attachments },
    onCancel: () => agent.cancelActiveRun(),
    onError: (error) => console.error("[Harness Console]", error),
  });

  return (
    <AssistantRuntimeProvider runtime={runtime}>
      {children}
    </AssistantRuntimeProvider>
  );
}
