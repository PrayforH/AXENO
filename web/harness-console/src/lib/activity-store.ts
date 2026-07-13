"use client";

import { useSyncExternalStore } from "react";
import type { RunActivity } from "./activity-schema";
import { activityItemSchema, runActivitySchema } from "./activity-schema";

export type ActivityPatchOperation = {
  op: string;
  path: string;
  value?: unknown;
};

let snapshot: RunActivity | undefined;
const listeners = new Set<() => void>();

export const activityStore = {
  clear() {
    if (snapshot === undefined) return;
    snapshot = undefined;
    for (const listener of listeners) listener();
  },
  publish(activity: RunActivity) {
    snapshot = activity;
    for (const listener of listeners) listener();
  },
  patch(operations: readonly ActivityPatchOperation[]) {
    if (!snapshot) return;
    const next: RunActivity = {
      ...snapshot,
      items: [...snapshot.items],
      metrics: { ...snapshot.metrics },
    };
    for (const operation of operations) {
      if (
        operation.op === "add" &&
        operation.path === "/items/-"
      ) {
        const item = activityItemSchema.safeParse(operation.value);
        if (item.success) next.items.push(item.data);
        continue;
      }
      if (
        (operation.op === "add" || operation.op === "replace") &&
        operation.path === "/status" &&
        typeof operation.value === "string"
      ) {
        next.status = operation.value;
        continue;
      }
      const metric = operation.path.match(/^\/metrics\/([^/]+)$/);
      if (metric && (operation.op === "add" || operation.op === "replace")) {
        next.metrics[metric[1].replaceAll("~1", "/").replaceAll("~0", "~")] =
          operation.value;
      }
    }
    const parsed = runActivitySchema.safeParse(next);
    if (parsed.success) this.publish(parsed.data);
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
