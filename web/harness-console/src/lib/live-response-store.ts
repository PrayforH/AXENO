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

// The provider does not label text as "commentary" or "final" up front. In
// practice, a short tool preface is followed by TOOL_CALL_START within a
// fraction of a second. Hold that ambiguous opening briefly so it can move
// directly into Activity without first flashing in the answer slot.
export const RESPONSE_CANDIDATE_HOLD_MS = 1_000;
const RESPONSE_EARLY_RELEASE_CHARS = 240;

type MessageDisposition = "idle" | "candidate" | "response" | "activity";

let snapshot = emptySnapshot;
const listeners = new Set<() => void>();
let pendingMessageId: string | undefined;
let pendingDelta = "";
let scheduledFrame: number | undefined;
let candidateTimer: ReturnType<typeof setTimeout> | undefined;
let disposition: MessageDisposition = "idle";

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
    status: snapshot.status === "complete" ? "complete" : "streaming",
    visible,
  });
}

function cancelCandidateTimer() {
  if (candidateTimer === undefined) return;
  globalThis.clearTimeout(candidateTimer);
  candidateTimer = undefined;
}

function promoteCandidate() {
  if (disposition !== "candidate") return;
  cancelCandidateTimer();
  disposition = "response";
  flushPendingDelta(true);
  if (!snapshot.visible && snapshot.text.trim()) {
    publish({ ...snapshot, visible: true });
  }
}

function cancelScheduledFrame() {
  if (scheduledFrame === undefined) return;
  globalThis.cancelAnimationFrame?.(scheduledFrame);
  scheduledFrame = undefined;
}

function schedulePendingDelta() {
  if (scheduledFrame !== undefined) return;
  if (typeof globalThis.requestAnimationFrame !== "function") {
    flushPendingDelta(disposition === "response");
    return;
  }
  scheduledFrame = globalThis.requestAnimationFrame(() =>
    flushPendingDelta(disposition === "response"),
  );
}

function scheduleCandidatePromotion() {
  if (candidateTimer !== undefined || disposition !== "candidate") return;
  candidateTimer = globalThis.setTimeout(
    promoteCandidate,
    RESPONSE_CANDIDATE_HOLD_MS,
  );
}

export const liveResponseStore = {
  clear() {
    cancelScheduledFrame();
    cancelCandidateTimer();
    pendingMessageId = undefined;
    pendingDelta = "";
    disposition = "idle";
    if (snapshot === emptySnapshot) return;
    publish(emptySnapshot);
  },
  startRun(runId: string) {
    cancelScheduledFrame();
    cancelCandidateTimer();
    pendingMessageId = undefined;
    pendingDelta = "";
    disposition = "idle";
    publish({
      runId,
      text: "",
      status: "streaming",
      visible: false,
    });
  },
  startMessage(messageId: string) {
    flushPendingDelta(false);
    cancelCandidateTimer();
    disposition = "candidate";
    publish({
      runId: snapshot.runId,
      messageId,
      text: "",
      status: "streaming",
      visible: false,
    });
  },
  append(messageId: string, delta: string) {
    if (!delta) return;
    if (pendingMessageId && pendingMessageId !== messageId) {
      flushPendingDelta(disposition === "response");
    }
    pendingMessageId = messageId;
    pendingDelta += delta;
    schedulePendingDelta();
    if (
      disposition === "candidate" &&
      snapshot.text.length + pendingDelta.length >= RESPONSE_EARLY_RELEASE_CHARS
    ) {
      promoteCandidate();
      return;
    }
    scheduleCandidatePromotion();
  },
  hideForTool() {
    cancelCandidateTimer();
    disposition = "activity";
    flushPendingDelta(false);
    if (!snapshot.text) return;
    publish({ ...snapshot, visible: false });
  },
  completeMessage(messageId: string) {
    flushPendingDelta(disposition === "response");
    if (snapshot.messageId !== messageId) return;
    publish({ ...snapshot, status: "complete" });
  },
  completeRun() {
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
  failRun() {
    cancelScheduledFrame();
    cancelCandidateTimer();
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
