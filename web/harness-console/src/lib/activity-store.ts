"use client";

import { useSyncExternalStore } from "react";
import type { RunActivity } from "./activity-schema";

let snapshot: RunActivity | undefined;
const listeners = new Set<() => void>();

export const activityStore = {
  publish(activity: RunActivity) {
    snapshot = activity;
    for (const listener of listeners) listener();
  },
  subscribe(listener: () => void) {
    listeners.add(listener);
    return () => listeners.delete(listener);
  },
  getSnapshot() {
    return snapshot;
  },
};

export function useRunActivity(): RunActivity | undefined {
  return useSyncExternalStore(
    activityStore.subscribe,
    activityStore.getSnapshot,
    () => undefined,
  );
}
