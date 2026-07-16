import { existsSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { runActivitySchema, type RunActivity } from "../src/lib/activity-schema";

function activity(
  status: string,
  items: Array<{
    id: string;
    event_type: string;
    kind?: "run" | "analysis" | "tool" | "subagent" | "artifact" | "result" | "error";
    status?: string;
    title?: string;
    sequence: number;
    metadata?: Record<string, unknown>;
  }>,
): RunActivity {
  return runActivitySchema.parse({
    run_id: "run-view",
    status,
    started_at: "2026-07-14T00:00:00Z",
    items: items.map((item) => ({
      kind: "run",
      status: "running",
      title: item.event_type,
      timestamp: `2026-07-14T00:00:0${item.sequence}Z`,
      metadata: {},
      ...item,
    })),
    metrics: {},
  });
}

async function moduleUnderTest() {
  expect(existsSync("src/lib/run-view-model.ts")).toBe(true);
  return import("../src/lib/run-view-model");
}

describe("run view model", () => {
  it("keeps terminal state monotonic when stale running activity arrives", async () => {
    const { reduceRunViewModel } = await moduleUnderTest();
    const running = reduceRunViewModel(
      undefined,
      activity("running", [
        { id: "run-start", event_type: "run.running", sequence: 1 },
      ]),
    );
    const completed = reduceRunViewModel(
      running,
      activity("succeeded", [
        { id: "run-finished", event_type: "run.succeeded", sequence: 2 },
      ]),
    );
    const afterStale = reduceRunViewModel(
      completed,
      activity("running", [
        { id: "stale", event_type: "run.running", sequence: 1 },
      ]),
    );

    expect(completed.phase).toBe("completed");
    expect(afterStale.phase).toBe("completed");
  });

  it("distinguishes model result from the durable run terminal", async () => {
    const { reduceRunViewModel } = await moduleUnderTest();
    const model = reduceRunViewModel(
      undefined,
      activity("succeeded", [
        {
          id: "runtime-result",
          event_type: "runtime.result",
          kind: "result",
          status: "succeeded",
          sequence: 2,
        },
      ]),
    );

    expect(model.phase).toBe("running");
  });

  it("tracks pending approval and returns to running after a decision", async () => {
    const { reduceRunViewModel } = await moduleUnderTest();
    const waiting = reduceRunViewModel(
      undefined,
      activity("waiting", [
        {
          id: "approval-request",
          event_type: "approval.requested",
          kind: "tool",
          status: "waiting",
          sequence: 2,
          metadata: { approval_id: "approval-1", tool_call_id: "tool-1" },
        },
      ]),
    );
    const resumed = reduceRunViewModel(
      waiting,
      activity("running", [
        {
          id: "approval-rejected",
          event_type: "approval.rejected",
          kind: "tool",
          status: "failed",
          sequence: 3,
          metadata: { approval_id: "approval-1" },
        },
      ]),
    );

    expect(waiting.phase).toBe("waiting_approval");
    expect(waiting.pendingApprovalId).toBe("approval-1");
    expect(resumed.phase).toBe("running");
    expect(resumed.pendingApprovalId).toBeUndefined();
  });

  it("groups distinct subagent tasks and pairs tools with real results", async () => {
    const { reduceRunViewModel } = await moduleUnderTest();
    const model = reduceRunViewModel(
      undefined,
      activity("running", [
        {
          id: "task-start",
          event_type: "subagent.started",
          kind: "subagent",
          sequence: 1,
          metadata: { task_id: "task-1", parent_tool_use_id: "parent-1" },
        },
        {
          id: "tool-start",
          event_type: "tool.request",
          kind: "tool",
          sequence: 2,
          metadata: { tool_call_id: "tool-1", name: "Read" },
        },
        {
          id: "tool-allowed",
          event_type: "tool.allowed",
          kind: "tool",
          sequence: 3,
          metadata: { tool_call_id: "tool-1" },
        },
        {
          id: "tool-result",
          event_type: "tool.result",
          kind: "tool",
          status: "succeeded",
          sequence: 4,
          metadata: { tool_call_id: "tool-1" },
        },
      ]),
    );

    expect(model.tasks).toHaveLength(1);
    expect(model.tasks[0]).toMatchObject({ id: "task-1", parentId: "parent-1" });
    expect(model.tools).toEqual([
      expect.objectContaining({ id: "tool-1", name: "Read", status: "completed" }),
    ]);
    expect(model.toolCount).toBe(1);
    expect(model.taskCount).toBe(1);
  });

  it("merges a delegation tool request into its real SDK subagent task", async () => {
    const { reduceRunViewModel } = await moduleUnderTest();
    const model = reduceRunViewModel(
      undefined,
      activity("succeeded", [
        {
          id: "delegate-request",
          event_type: "tool.request",
          kind: "subagent",
          status: "running",
          title: "调用 Agent",
          sequence: 1,
          metadata: { tool_call_id: "call-1", name: "Agent" },
        },
        {
          id: "task-started",
          event_type: "subagent.started",
          kind: "subagent",
          status: "running",
          title: "子 Agent 正在执行",
          sequence: 2,
          metadata: { task_id: "task-1", parent_tool_use_id: "call-1" },
        },
        {
          id: "task-completed",
          event_type: "subagent.completed",
          kind: "subagent",
          status: "succeeded",
          title: "子 Agent 已完成",
          summary: "证据检查完成",
          sequence: 3,
          metadata: { task_id: "task-1", parent_tool_use_id: "call-1" },
        },
      ]),
    );

    expect(model.taskCount).toBe(1);
    expect(model.tasks).toEqual([
      expect.objectContaining({
        id: "task-1",
        parentId: "call-1",
        title: "证据检查完成",
        status: "completed",
      }),
    ]);
  });

  it("derives composer locking from the same run phase", async () => {
    const { selectComposerDisabled } = await moduleUnderTest();

    expect(selectComposerDisabled(undefined)).toBe(false);
    expect(selectComposerDisabled({ phase: "running" })).toBe(true);
    expect(selectComposerDisabled({ phase: "waiting_approval" })).toBe(true);
    expect(selectComposerDisabled({ phase: "completed" })).toBe(false);
    expect(selectComposerDisabled({ phase: "failed" })).toBe(false);
  });
});
