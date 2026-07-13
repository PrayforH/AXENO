import { describe, expect, it, vi } from "vitest";
import { activityStore } from "../src/lib/activity-store";
import { runActivitySchema } from "../src/lib/activity-schema";

describe("activity store", () => {
  it("shares the renderer's replayable activity with the run inspector", () => {
    const listener = vi.fn();
    const unsubscribe = activityStore.subscribe(listener);
    const activity = runActivitySchema.parse({
      run_id: "run-store",
      status: "running",
      started_at: "2026-07-13T00:00:00Z",
      items: [],
      metrics: {},
    });

    activityStore.publish(activity);

    expect(activityStore.getSnapshot()).toBe(activity);
    expect(listener).toHaveBeenCalledOnce();
    unsubscribe();
  });
});
