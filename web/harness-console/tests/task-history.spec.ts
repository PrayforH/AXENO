import { afterEach, describe, expect, it, vi } from "vitest";
import { activityStore } from "../src/lib/activity-store";
import { createThreadHistoryAdapter } from "../src/lib/task-history";

describe("thread history activity restoration", () => {
  afterEach(() => {
    activityStore.clear();
    vi.unstubAllGlobals();
  });

  it("publishes the durable run activity when a completed task reloads", async () => {
    const activity = {
      run_id: "run-history",
      status: "succeeded",
      started_at: "2026-07-16T00:00:00Z",
      items: [],
      metrics: { turns: 2 },
    };
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify({
            thread_id: "thread-history",
            messages: [
              { id: "user-1", role: "user", content: "你好" },
              {
                id: "assistant-1",
                role: "assistant",
                content: "你好！",
                toolCalls: [
                  {
                    id: "harness-activity-run-history",
                    type: "function",
                    function: {
                      name: "harness_run_activity",
                      arguments: JSON.stringify({ activity }),
                    },
                  },
                ],
              },
              {
                id: "tool-activity-run-history",
                role: "tool",
                content: '{"status":"ready"}',
                toolCallId: "harness-activity-run-history",
              },
            ],
          }),
          { status: 200, headers: { "Content-Type": "application/json" } },
        ),
      ),
    );

    await createThreadHistoryAdapter("thread-history").load();

    expect(activityStore.getSnapshot()).toMatchObject({
      run_id: "run-history",
      status: "succeeded",
      metrics: { turns: 2 },
    });
  });
});
