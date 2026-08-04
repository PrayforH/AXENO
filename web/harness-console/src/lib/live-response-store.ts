"use client";

import { useSyncExternalStore } from "react";
import { isActiveRuntimeThread } from "./runtime-thread-scope";

export type LiveResponseStatus =
  | "idle"
  | "streaming"
  | "complete"
  | "error";

export interface LiveResponseSnapshot {
  threadId?: string;
  runId?: string;
  messageId?: string;
  text: string;
  status: LiveResponseStatus;
  visible: boolean;
}

const emptySnapshot: LiveResponseSnapshot = Object.freeze({
  text: "",
  status: "idle",
  visible: false,
});

// The provider does not label text as "commentary" or "final" up front. Keep a
// short candidate out of the response slot because these are normally progress
// prefaces followed by a tool. Once it grows into a substantive answer, stream
// it; if a tool still follows, Activity retains it as processing commentary.

type MessageDisposition = "idle" | "candidate" | "response" | "activity";

let snapshot = emptySnapshot;
const listeners = new Set<() => void>();
let pendingMessageId: string | undefined;
let pendingDelta = "";
let scheduledFrame: number | undefined;
let scheduledWatchdog: ReturnType<typeof setTimeout> | undefined;
let disposition: MessageDisposition = "idle";
const FRAME_WATCHDOG_MS = 120;
const RESPONSE_CANDIDATE_MIN_CHARS = 160;

function publish(next: LiveResponseSnapshot) {
  if (
    snapshot.runId === next.runId &&
    snapshot.messageId === next.messageId &&
    snapshot.text === next.text &&
    snapshot.status === next.status &&
    snapshot.visible === next.visible
  ) {
    return;
  }
  snapshot = next;
  for (const listener of listeners) listener();
}

function flushPendingDelta(visible = true) {
  const frame = scheduledFrame;
  scheduledFrame = undefined;
  if (frame !== undefined) globalThis.cancelAnimationFrame?.(frame);
  if (scheduledWatchdog !== undefined) {
    globalThis.clearTimeout(scheduledWatchdog);
    scheduledWatchdog = undefined;
  }
  if (!pendingMessageId || !pendingDelta) return;
  const messageId = pendingMessageId;
  const delta = pendingDelta;
  pendingMessageId = undefined;
  pendingDelta = "";
  const sameMessage = snapshot.messageId === messageId;
  const text = `${sameMessage ? snapshot.text : ""}${delta}`;
  const candidateReady =
    disposition !== "candidate" ||
    snapshot.visible ||
    text.trim().length >= RESPONSE_CANDIDATE_MIN_CHARS;
  publish({
    threadId: snapshot.threadId,
    runId: snapshot.runId,
    messageId,
    text,
    status: snapshot.status === "complete" ? "complete" : "streaming",
    visible: visible && candidateReady,
  });
}

function promoteCandidate() {
  if (disposition !== "candidate") return;
  disposition = "response";
  flushPendingDelta(true);
  if (!snapshot.visible && snapshot.text.trim()) {
    publish({ ...snapshot, visible: true });
  }
}

function cancelScheduledFrame() {
  if (scheduledFrame !== undefined) {
    globalThis.cancelAnimationFrame?.(scheduledFrame);
    scheduledFrame = undefined;
  }
  if (scheduledWatchdog !== undefined) {
    globalThis.clearTimeout(scheduledWatchdog);
    scheduledWatchdog = undefined;
  }
}

function schedulePendingDelta() {
  if (scheduledFrame !== undefined) return;
  if (typeof globalThis.requestAnimationFrame !== "function") {
    flushPendingDelta(disposition !== "activity");
    return;
  }
  scheduledFrame = globalThis.requestAnimationFrame(() =>
    flushPendingDelta(disposition !== "activity"),
  );
  // Browsers can heavily throttle or stop animation frames for a busy or
  // backgrounded tab. Never let the only copy of streamed text wait on paint.
  scheduledWatchdog = globalThis.setTimeout(
    () => flushPendingDelta(disposition !== "activity"),
    FRAME_WATCHDOG_MS,
  );
}

export const liveResponseStore = {
  clear(threadId?: string) {
    if (!isActiveRuntimeThread(threadId)) return;
    cancelScheduledFrame();
    pendingMessageId = undefined;
    pendingDelta = "";
    disposition = "idle";
    if (snapshot === emptySnapshot) return;
    publish(emptySnapshot);
  },
  startRun(runId: string, threadId?: string) {
    if (!isActiveRuntimeThread(threadId)) return;
    cancelScheduledFrame();
    pendingMessageId = undefined;
    pendingDelta = "";
    disposition = "idle";
    publish({
      threadId,
      runId,
      text: "",
      status: "streaming",
      visible: false,
    });
  },
  startMessage(messageId: string, threadId?: string) {
    if (!isActiveRuntimeThread(threadId)) return;
    flushPendingDelta(false);
    disposition = "candidate";
    publish({
      threadId: snapshot.threadId ?? threadId,
      runId: snapshot.runId,
      messageId,
      text: "",
      status: "streaming",
      visible: false,
    });
  },
  append(messageId: string, delta: string, threadId?: string) {
    if (!isActiveRuntimeThread(threadId)) return;
    if (!delta) return;
    if (pendingMessageId && pendingMessageId !== messageId) {
      flushPendingDelta(disposition !== "activity");
    }
    pendingMessageId = messageId;
    pendingDelta += delta;
    schedulePendingDelta();
  },
  hideForTool(threadId?: string) {
    if (!isActiveRuntimeThread(threadId)) return;
    flushPendingDelta(false);
    // A tool can start before the provider has emitted any assistant prose.
    // In that case there is no response candidate to reclassify. Keeping the
    // candidate disposition lets the terminal-only response projection reuse
    // the stable message and become visible when the Run finishes.
    if (!snapshot.text) return;
    disposition = "activity";
    publish({ ...snapshot, visible: false });
  },
  completeMessage(messageId: string, threadId?: string) {
    if (!isActiveRuntimeThread(threadId)) return;
    flushPendingDelta(disposition !== "activity");
    if (snapshot.messageId !== messageId) return;
    publish({ ...snapshot, status: "complete" });
  },
  completeRun(threadId?: string) {
    if (!isActiveRuntimeThread(threadId)) return;
    cancelScheduledFrame();
    if (disposition === "candidate") promoteCandidate();
    else flushPendingDelta(disposition === "response");
    publish({
      ...snapshot,
      status: "complete",
      visible:
        disposition === "response" && Boolean(snapshot.text.trim()),
    });
  },
  failRun(threadId?: string) {
    if (!isActiveRuntimeThread(threadId)) return;
    cancelScheduledFrame();
    flushPendingDelta(disposition === "response");
    publish({
      ...snapshot,
      status: "error",
      visible:
        disposition === "response" && Boolean(snapshot.text.trim()),
    });
  },
  subscribe(listener: () => void) {
    listeners.add(listener);
    return () => listeners.delete(listener);
  },
  getSnapshot() {
    return snapshot;
  },
};

export function useLiveResponse(): LiveResponseSnapshot {
  return useSyncExternalStore(
    liveResponseStore.subscribe,
    liveResponseStore.getSnapshot,
    () => emptySnapshot,
  );
}
