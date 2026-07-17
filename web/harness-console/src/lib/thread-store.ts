const THREAD_STORAGE_KEY = "harness-console-thread";
const THREAD_AGENT_STORAGE_PREFIX = "harness-console-thread-agent:";

export interface ThreadStorage {
  getItem(key: string): string | null;
  setItem(key: string, value: string): void;
}

export interface ThreadAgentBinding {
  name: string;
  version: string;
  displayName?: string;
  domain?: string;
}

type IdFactory = () => string;

export function loadOrCreateThread(
  storage: ThreadStorage,
  createId: IdFactory = () => crypto.randomUUID(),
): string {
  const existing = storage.getItem(THREAD_STORAGE_KEY);
  return existing ?? createNewThread(storage, createId);
}

export function createNewThread(
  storage: ThreadStorage,
  createId: IdFactory = () => crypto.randomUUID(),
): string {
  const threadId = createId();
  storage.setItem(THREAD_STORAGE_KEY, threadId);
  return threadId;
}

export function selectThread(storage: ThreadStorage, threadId: string): string {
  storage.setItem(THREAD_STORAGE_KEY, threadId);
  return threadId;
}

export function bindThreadAgent(
  storage: ThreadStorage,
  threadId: string,
  agent: ThreadAgentBinding,
): void {
  storage.setItem(
    `${THREAD_AGENT_STORAGE_PREFIX}${threadId}`,
    JSON.stringify(agent),
  );
}

export function loadThreadAgent(
  storage: ThreadStorage,
  threadId: string,
): ThreadAgentBinding | null {
  const raw = storage.getItem(`${THREAD_AGENT_STORAGE_PREFIX}${threadId}`);
  if (!raw) return null;
  try {
    const value = JSON.parse(raw) as Partial<ThreadAgentBinding>;
    if (
      typeof value.name !== "string" ||
      !value.name ||
      typeof value.version !== "string" ||
      !value.version
    ) {
      return null;
    }
    return {
      name: value.name,
      version: value.version,
      ...(typeof value.displayName === "string"
        ? { displayName: value.displayName }
        : {}),
      ...(typeof value.domain === "string" ? { domain: value.domain } : {}),
    };
  } catch {
    return null;
  }
}
