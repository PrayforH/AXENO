import { describe, expect, it } from "vitest";
import {
  loadTaskModelOverride,
  saveTaskModelOverride,
} from "../src/lib/task-model-catalog";

function memoryStorage() {
  const values = new Map<string, string>();
  return {
    getItem: (key: string) => values.get(key) ?? null,
    setItem: (key: string, value: string) => values.set(key, value),
    removeItem: (key: string) => values.delete(key),
  };
}

describe("task model selection", () => {
  it("persists a task-scoped route without changing the Agent", () => {
    const storage = memoryStorage();

    saveTaskModelOverride(storage, "thread-1", "minimax-m3");

    expect(loadTaskModelOverride(storage, "thread-1")).toBe("minimax-m3");
    expect(loadTaskModelOverride(storage, "thread-2")).toBeNull();
  });

  it("clears follow-Agent selection and rejects malformed stored routes", () => {
    const storage = memoryStorage();
    storage.setItem("agent-studio.task-model:thread-1", "../../secret");
    expect(loadTaskModelOverride(storage, "thread-1")).toBeNull();

    saveTaskModelOverride(storage, "thread-1", "minimax-m3");
    saveTaskModelOverride(storage, "thread-1", null);
    expect(loadTaskModelOverride(storage, "thread-1")).toBeNull();
  });
});
