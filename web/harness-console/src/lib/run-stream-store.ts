"use client";

import { useSyncExternalStore } from "react";

export type RunStreamStatus = "idle" | "running" | "complete" | "error";

export interface RunStreamSnapshot {
  runId?: string;
  status: RunStreamStatus;
}

const emptySnapshot: RunStreamSnapshot = Object.freeze({
  status: "idle",
});

let snapshot = emptySnapshot;
const listeners = new Set<() => void>();

function publish(next: RunStreamSnapshot) {
  if (snapshot.runId === next.runId && snapshot.status === next.status) return;
  snapshot = next;
  for (const listener of listeners) listener();
}

function settle(runId: string | undefined, status: "complete" | "error") {
  if (runId && snapshot.runId && snapshot.runId !== runId) return;
  publish({
    runId: runId ?? snapshot.runId,
    status,
  });
}

export const runStreamStore = {
  clear() {
    publish(emptySnapshot);
  },
  startRun(runId: string) {
    publish({ runId, status: "running" });
  },
  completeRun(runId?: string) {
    settle(runId, "complete");
  },
  failRun(runId?: string) {
    settle(runId, "error");
  },
  subscribe(listener: () => void) {
    listeners.add(listener);
    return () => listeners.delete(listener);
  },
  getSnapshot() {
    return snapshot;
  },
};

export function useRunStream(): RunStreamSnapshot {
  return useSyncExternalStore(
    runStreamStore.subscribe,
    runStreamStore.getSnapshot,
    () => emptySnapshot,
  );
}
