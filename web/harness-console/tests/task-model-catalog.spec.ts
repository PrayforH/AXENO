import { afterEach, describe, expect, it, vi } from "vitest";
import {
  loadTaskModelRoutes,
  loadTaskModelOverride,
  saveTaskModelOverride,
} from "../src/lib/task-model-catalog";

afterEach(() => vi.unstubAllGlobals());

function memoryStorage() {
  const values = new Map<string, string>();
  return {
    getItem: (key: string) => values.get(key) ?? null,
    setItem: (key: string, value: string) => values.set(key, value),
    removeItem: (key: string) => values.delete(key),
  };
}

describe("task model selection", () => {
  it("exposes DeepSeek Pro and Flash as separate task routes", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({
      modelRoutes: [
        {
          routeId: "new-api-default",
          label: "DeepSeek V4（兼容路由）",
          provider: "deepseek",
          models: ["deepseek-v4-pro"],
          capabilities: ["streaming", "tool_use"],
          enabled: false,
        },
        {
          routeId: "deepseek-v4-flash",
          label: "DeepSeek V4 Flash",
          provider: "deepseek",
          models: ["deepseek-v4-flash"],
          capabilities: ["streaming", "tool_use"],
          enabled: true,
        },
        {
          routeId: "deepseek-v4-pro",
          label: "DeepSeek V4 Pro",
          provider: "deepseek",
          models: ["deepseek-v4-pro"],
          capabilities: ["streaming", "tool_use"],
          enabled: true,
        },
      ],
    }), { status: 200 })));

    await expect(loadTaskModelRoutes()).resolves.toEqual([
      expect.objectContaining({ id: "deepseek-v4-flash", model: "deepseek-v4-flash" }),
      expect.objectContaining({ id: "deepseek-v4-pro", model: "deepseek-v4-pro" }),
    ]);
  });

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
