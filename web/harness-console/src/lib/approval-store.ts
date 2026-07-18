"use client";

import { useSyncExternalStore } from "react";
import type { ApprovalDetails } from "../components/approval-card";

export interface PendingApprovalSnapshot {
  details?: ApprovalDetails;
  visible: boolean;
}

const emptySnapshot: PendingApprovalSnapshot = Object.freeze({
  visible: false,
});

let snapshot = emptySnapshot;
const settledApprovalIds = new Set<string>();
const listeners = new Set<() => void>();

function publish(next: PendingApprovalSnapshot) {
  snapshot = next;
  for (const listener of listeners) listener();
}

export const approvalStore = {
  show(details: ApprovalDetails) {
    if (settledApprovalIds.has(details.approval_id)) return;
    if (
      snapshot.visible &&
      snapshot.details?.approval_id === details.approval_id
    ) {
      return;
    }
    publish({ details, visible: true });
  },
  settle(approvalId: string) {
    settledApprovalIds.add(approvalId);
    this.clear(approvalId);
  },
  clear(approvalId?: string) {
    if (
      snapshot === emptySnapshot ||
      (approvalId && snapshot.details?.approval_id !== approvalId)
    ) {
      return;
    }
    publish(emptySnapshot);
  },
  reset() {
    settledApprovalIds.clear();
    this.clear();
  },
  subscribe(listener: () => void) {
    listeners.add(listener);
    return () => listeners.delete(listener);
  },
  getSnapshot() {
    return snapshot;
  },
};

export function usePendingApproval(): PendingApprovalSnapshot {
  return useSyncExternalStore(
    approvalStore.subscribe,
    approvalStore.getSnapshot,
    () => emptySnapshot,
  );
}
