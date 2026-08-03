"use client";

import {
  AssistantRuntimeProvider,
  WebSpeechSynthesisAdapter,
} from "@assistant-ui/react";
import { useAgUiRuntime } from "@assistant-ui/react-ag-ui";
import type { ReactNode } from "react";
import { useLayoutEffect, useMemo } from "react";
import { activityStore, useRunViewModel } from "../lib/activity-store";
import { HarnessHttpAgent } from "../lib/harness-agent";
import { createInputAttachmentAdapter } from "../lib/input-attachment-adapter";
import { liveResponseStore } from "../lib/live-response-store";
import { runStreamStore } from "../lib/run-stream-store";
import { runReuseStore } from "../lib/run-reuse-store";
import { uploadFeedbackStore } from "../lib/upload-feedback-store";
import { createThreadHistoryAdapter } from "../lib/task-history";
import { activateRuntimeThread } from "../lib/runtime-thread-scope";
import type { TaskModelRoute } from "../lib/task-model-catalog";
import { TaskModelProvider } from "./task-model-context";

export function AssistantRuntimeShell({
  threadId,
  agentName,
  agentVersion,
  agentOwnerUserId,
  spaceId,
  agentDefaultModelRoute,
  modelRoutes,
  modelRouteOverride,
  onModelRouteOverrideChange,
  children,
}: {
  threadId: string;
  agentName: string;
  agentVersion: string;
  agentOwnerUserId?: string;
  spaceId?: string;
  agentDefaultModelRoute: string | null;
  modelRoutes: TaskModelRoute[];
  modelRouteOverride: string | null;
  onModelRouteOverrideChange: (routeId: string | null) => void;
  children: ReactNode;
}) {
  const runView = useRunViewModel();
  const agent = useMemo(() => {
    const query = new URLSearchParams({
      agent_name: agentName,
      agent_version: agentVersion,
    });
    if (agentOwnerUserId) query.set("agent_owner_user_id", agentOwnerUserId);
    if (spaceId) query.set("space_id", spaceId);
    const next = new HarnessHttpAgent({
      url: `/api/agui?${query.toString()}`,
      modelRouteOverride,
    });
    next.threadId = threadId;
    return next;
  }, [agentName, agentOwnerUserId, agentVersion, modelRouteOverride, spaceId, threadId]);
  const attachments = useMemo(() => createInputAttachmentAdapter(), []);
  const speech = useMemo(() => new WebSpeechSynthesisAdapter(), []);
  const history = useMemo(() => createThreadHistoryAdapter(threadId), [threadId]);
  useLayoutEffect(() => {
    activateRuntimeThread(threadId);
    activityStore.clear();
    liveResponseStore.clear();
    runStreamStore.clear();
    runReuseStore.clear();
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
      <TaskModelProvider
        routes={modelRoutes}
        agentDefaultRouteId={agentDefaultModelRoute}
        overrideRouteId={modelRouteOverride}
        onOverrideChange={onModelRouteOverrideChange}
      >
        <div
          className="assistant-runtime-shell"
          data-run-phase={runView?.phase ?? "idle"}
        >
          {children}
        </div>
      </TaskModelProvider>
    </AssistantRuntimeProvider>
  );
}
