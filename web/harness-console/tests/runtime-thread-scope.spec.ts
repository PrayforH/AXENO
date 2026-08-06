import { afterEach, describe, expect, it } from "vitest";
import { activityStore } from "../src/lib/activity-store";
import { runActivitySchema } from "../src/lib/activity-schema";
import { approvalStore } from "../src/lib/approval-store";
import { liveResponseStore } from "../src/lib/live-response-store";
import {
  activateRuntimeThread,
  resetRuntimeThreadScope,
} from "../src/lib/runtime-thread-scope";
import { runStreamStore } from "../src/lib/run-stream-store";

describe("runtime thread scope", () => {
  afterEach(() => {
    resetRuntimeThreadScope();
    activityStore.clear();
    approvalStore.reset();
    liveResponseStore.clear();
    runStreamStore.clear();
  });

  it("ignores late live and activity events from a background thread", () => {
    activateRuntimeThread("thread-current");
    activityStore.clear();
    liveResponseStore.clear();
    runStreamStore.clear();

    liveResponseStore.startRun("run-background", "thread-background");
    runStreamStore.startRun("run-background", "thread-background");
    activityStore.publish(
      runActivitySchema.parse({
        run_id: "run-background",
        status: "running",
        started_at: "2026-07-23T00:00:00Z",
        items: [],
        metrics: {},
      }),
      "thread-background",
    );

    expect(liveResponseStore.getSnapshot().status).toBe("idle");
    expect(runStreamStore.getSnapshot().status).toBe("idle");
    expect(activityStore.getSnapshot()).toBeUndefined();

    liveResponseStore.startRun("run-current", "thread-current");
    runStreamStore.startRun("run-current", "thread-current");
    expect(liveResponseStore.getSnapshot()).toMatchObject({
      threadId: "thread-current",
      runId: "run-current",
    });
    expect(runStreamStore.getSnapshot()).toMatchObject({
      threadId: "thread-current",
      runId: "run-current",
    });
  });

  it("does not surface another thread's approval", () => {
    activateRuntimeThread("thread-current");
    approvalStore.reset();

    approvalStore.show(
      {
        approval_id: "approval-background",
        run_id: "run-background",
        tool_call_id: "tool-background",
        reason: "background",
      },
      "thread-background",
    );

    expect(approvalStore.getSnapshot().visible).toBe(false);
  });
});
