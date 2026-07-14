import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { ActivitySummary } from "../src/components/activity-summary";
import { runActivitySchema } from "../src/lib/activity-schema";

const activity = runActivitySchema.parse({
  run_id: "run-ribbon",
  status: "running",
  started_at: "2026-07-14T00:00:00Z",
  metrics: {},
  items: [
    {
      id: "run-start",
      event_type: "run.running",
      kind: "run",
      status: "running",
      title: "Agent 开始执行",
      timestamp: "2026-07-14T00:00:01Z",
      sequence: 1,
      metadata: {},
    },
    {
      id: "task-a-start",
      event_type: "subagent.started",
      kind: "subagent",
      status: "running",
      title: "子 Agent 正在执行",
      summary: "分析依赖关系",
      timestamp: "2026-07-14T00:00:02Z",
      sequence: 2,
      metadata: { task_id: "task-a", parent_tool_use_id: "root" },
    },
    {
      id: "task-a-complete",
      event_type: "subagent.completed",
      kind: "subagent",
      status: "succeeded",
      title: "子 Agent 已完成",
      summary: "分析依赖关系",
      timestamp: "2026-07-14T00:00:03Z",
      sequence: 3,
      metadata: { task_id: "task-a", parent_tool_use_id: "root" },
    },
    {
      id: "task-b-start",
      event_type: "subagent.started",
      kind: "subagent",
      status: "running",
      title: "子 Agent 正在执行",
      summary: "检查审批边界",
      timestamp: "2026-07-14T00:00:04Z",
      sequence: 4,
      metadata: { task_id: "task-b", parent_tool_use_id: "root" },
    },
    {
      id: "tool-one",
      event_type: "tool.request",
      kind: "tool",
      status: "running",
      title: "调用 Read",
      timestamp: "2026-07-14T00:00:05Z",
      sequence: 5,
      metadata: { tool_call_id: "tool-1", name: "Read" },
    },
    {
      id: "tool-two",
      event_type: "tool.request",
      kind: "tool",
      status: "running",
      title: "调用 Grep",
      timestamp: "2026-07-14T00:00:06Z",
      sequence: 6,
      metadata: { tool_call_id: "tool-2", name: "Grep" },
    },
  ],
});

describe("execution ribbon", () => {
  it("collapses the run into one native disclosure summary by default", () => {
    const html = renderToStaticMarkup(<ActivitySummary activity={activity} />);

    expect(html).toContain('<details class="execution-ribbon phase-running"');
    expect(html).not.toContain('<details class="execution-ribbon phase-running" open');
    expect(html).toContain("正在执行");
    expect(html).toContain("2 个工具");
    expect(html).toContain("2 个子任务");
    expect(html).toContain("6s");
  });

  it("keeps the active task open and completed task collapsed in the task tree", () => {
    const html = renderToStaticMarkup(<ActivitySummary activity={activity} />);

    expect(html).toContain(
      '<details class="execution-task task-completed"><summary>',
    );
    expect(html).toContain(
      '<details class="execution-task task-running" open=""><summary>',
    );
    expect(html).toContain("分析依赖关系");
    expect(html).toContain("检查审批边界");
    expect(html).toContain("Read");
    expect(html).toContain("Grep");
    expect(html).not.toContain("subagent.started");
  });
});
