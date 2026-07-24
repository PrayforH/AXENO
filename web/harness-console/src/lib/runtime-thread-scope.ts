"use client";

let activeThreadId: string | undefined;

export function activateRuntimeThread(threadId: string) {
  const changed = activeThreadId !== threadId;
  activeThreadId = threadId;
  return changed;
}

export function isActiveRuntimeThread(threadId?: string) {
  return threadId === undefined || activeThreadId === undefined || threadId === activeThreadId;
}

export function resetRuntimeThreadScope() {
  activeThreadId = undefined;
}
