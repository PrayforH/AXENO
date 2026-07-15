"use client";

import { useCallback, useEffect, useState } from "react";

interface SessionSummary {
  session_id: string;
  agent_name: string;
  agent_version: string;
  created_at: string;
}

let cached: SessionSummary[] | null = null;
let loading = false;
const listeners = new Set<() => void>();

async function refreshSessions() {
  loading = true;
  try {
    const res = await fetch("/api/harness/sessions?limit=20");
    if (res.ok) {
      cached = await res.json();
    }
  } catch {
    // keep stale cache if available
  } finally {
    loading = false;
    for (const listener of listeners) listener();
  }
}

function subscribe(listener: () => void) {
  listeners.add(listener);
  return () => { listeners.delete(listener); };
}

function getSnapshot(): SessionSummary[] {
  return cached ?? [];
}

export function useRecentSessions(): {
  sessions: SessionSummary[];
  refresh: () => void;
  loading: boolean;
} {
  const [, setTick] = useState(0);

  useEffect(() => {
    const unsub = subscribe(() => setTick((t) => t + 1));
    return unsub;
  }, []);

  useEffect(() => {
    if (cached === null && !loading) {
      void refreshSessions();
    }
  }, []);

  const refresh = useCallback(() => {
    refreshSessions();
  }, []);

  return { sessions: getSnapshot(), refresh, loading };
}

export function invalidateSessionCache() {
  cached = null;
}
