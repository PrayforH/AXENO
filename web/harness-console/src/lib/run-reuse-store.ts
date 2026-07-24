"use client";

import { useSyncExternalStore } from "react";

export interface RunReuseNotice {
  runId: string;
  canonicalClientRunId: string;
}

const emptySnapshot: RunReuseNotice | null = null;
let snapshot: RunReuseNotice | null = emptySnapshot;
const listeners = new Set<() => void>();

function publish(next: RunReuseNotice | null) {
  snapshot = next;
  for (const listener of listeners) listener();
}

export const runReuseStore = {
  show(notice: RunReuseNotice) {
    publish(notice);
  },
  clear() {
    if (snapshot !== null) publish(null);
  },
  subscribe(listener: () => void) {
    listeners.add(listener);
    return () => listeners.delete(listener);
  },
  getSnapshot() {
    return snapshot;
  },
};

export function useRunReuseNotice(): RunReuseNotice | null {
  return useSyncExternalStore(
    runReuseStore.subscribe,
    runReuseStore.getSnapshot,
    () => emptySnapshot,
  );
}
