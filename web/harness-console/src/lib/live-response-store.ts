"use client";

import { useSyncExternalStore } from "react";

export type LiveResponseStatus =
  | "idle"
  | "streaming"
  | "complete"
  | "error";

export interface LiveResponseSnapshot {
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

let snapshot = emptySnapshot;
const listeners = new Set<() => void>();
let pendingMessageId: string | undefined;
let pendingDelta = "";
let scheduledFrame: number | undefined;

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

function flushPendingDelta() {
  const frame = scheduledFrame;
  scheduledFrame = undefined;
  if (frame !== undefined) globalThis.cancelAnimationFrame?.(frame);
  if (!pendingMessageId || !pendingDelta) return;
  const messageId = pendingMessageId;
  const delta = pendingDelta;
  pendingMessageId = undefined;
  pendingDelta = "";
  const sameMessage = snapshot.messageId === messageId;
  publish({
    runId: snapshot.runId,
    messageId,
    text: `${sameMessage ? snapshot.text : ""}${delta}`,
    status: "streaming",
    visible: true,
  });
}

function cancelScheduledFrame() {
  if (scheduledFrame === undefined) return;
  globalThis.cancelAnimationFrame?.(scheduledFrame);
  scheduledFrame = undefined;
}

function schedulePendingDelta() {
  if (scheduledFrame !== undefined) return;
  if (typeof globalThis.requestAnimationFrame !== "function") {
    flushPendingDelta();
    return;
  }
  scheduledFrame = globalThis.requestAnimationFrame(flushPendingDelta);
}

export const liveResponseStore = {
  clear() {
    cancelScheduledFrame();
    pendingMessageId = undefined;
    pendingDelta = "";
    if (snapshot === emptySnapshot) return;
    publish(emptySnapshot);
  },
  startRun(runId: string) {
    cancelScheduledFrame();
    pendingMessageId = undefined;
    pendingDelta = "";
    publish({
      runId,
      text: "",
      status: "streaming",
      visible: false,
    });
  },
  startMessage(messageId: string) {
    flushPendingDelta();
    publish({
      runId: snapshot.runId,
      messageId,
      text: "",
      status: "streaming",
      visible: true,
    });
  },
  append(messageId: string, delta: string) {
    if (!delta) return;
    if (pendingMessageId && pendingMessageId !== messageId) flushPendingDelta();
    pendingMessageId = messageId;
    pendingDelta += delta;
    schedulePendingDelta();
  },
  hideForTool() {
    flushPendingDelta();
    if (!snapshot.text) return;
    publish({ ...snapshot, visible: false });
  },
  completeMessage(messageId: string) {
    flushPendingDelta();
    if (snapshot.messageId !== messageId) return;
    publish({ ...snapshot, status: "complete" });
  },
  completeRun() {
    flushPendingDelta();
    publish({ ...snapshot, status: "complete" });
  },
  failRun() {
    flushPendingDelta();
    publish({ ...snapshot, status: "error" });
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
