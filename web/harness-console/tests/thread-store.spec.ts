import { describe, expect, it } from "vitest";
import { createNewThread, loadOrCreateThread } from "../src/lib/thread-store";

function memoryStorage(initial?: string) {
  let value = initial ?? null;
  return {
    getItem: () => value,
    setItem: (_key: string, next: string) => {
      value = next;
    },
    removeItem: () => {
      value = null;
    },
    value: () => value,
  };
}

describe("thread store", () => {
  it("restores the existing thread after refresh", () => {
    const storage = memoryStorage("thread-existing");

    expect(loadOrCreateThread(storage, () => "thread-new")).toBe("thread-existing");
    expect(storage.value()).toBe("thread-existing");
  });

  it("creates and persists a thread when none exists", () => {
    const storage = memoryStorage();

    expect(loadOrCreateThread(storage, () => "thread-created")).toBe("thread-created");
    expect(storage.value()).toBe("thread-created");
  });

  it("replaces the current thread only for a new conversation", () => {
    const storage = memoryStorage("thread-existing");

    expect(createNewThread(storage, () => "thread-replacement")).toBe(
      "thread-replacement",
    );
    expect(storage.value()).toBe("thread-replacement");
  });
});
