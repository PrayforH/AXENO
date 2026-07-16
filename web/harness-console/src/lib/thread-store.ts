const THREAD_STORAGE_KEY = "harness-console-thread";

export interface ThreadStorage {
  getItem(key: string): string | null;
  setItem(key: string, value: string): void;
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
