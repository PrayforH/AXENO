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

function publish(next: LiveResponseSnapshot) {
  snapshot = next;
  for (const listener of listeners) listener();
}

export const liveResponseStore = {
  clear() {
    if (snapshot === emptySnapshot) return;
    publish(emptySnapshot);
  },
  startRun(runId: string) {
    publish({
      runId,
      text: "",
      status: "streaming",
      visible: false,
    });
  },
  startMessage(messageId: string) {
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
    const sameMessage = snapshot.messageId === messageId;
    publish({
      runId: snapshot.runId,
      messageId,
      text: `${sameMessage ? snapshot.text : ""}${delta}`,
      status: "streaming",
      visible: true,
    });
  },
  hideForTool() {
    if (!snapshot.text) return;
    publish({ ...snapshot, visible: false });
  },
  completeMessage(messageId: string) {
    if (snapshot.messageId !== messageId) return;
    publish({ ...snapshot, status: "complete" });
  },
  completeRun() {
    publish({ ...snapshot, status: "complete" });
  },
  failRun() {
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
