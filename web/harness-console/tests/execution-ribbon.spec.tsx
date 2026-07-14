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

  it("uses user-readable section titles for expanded run details", () => {
    const routed = runActivitySchema.parse({
      ...activity,
      items: [
        ...activity.items,
        {
          id: "model-route",
          event_type: "model.route.selected",
          kind: "run",
          status: "succeeded",
          title: "模型路由已选择",
          summary: "claude-sonnet",
          timestamp: "2026-07-14T00:00:07Z",
          sequence: 7,
          metadata: { model: "claude-sonnet" },
        },
      ],
    });
    const html = renderToStaticMarkup(<ActivitySummary activity={routed} />);

    expect(html).toContain("子任务");
    expect(html).toContain("使用的工具");
    expect(html).toContain("运行模型");
    expect(html).not.toContain("子 Agent 任务");
    expect(html).not.toContain("<h4>工具</h4>");
  });

  it.each([
    ["approval.requested", "tool", "waiting", "等待审批"],
    ["run.failed", "error", "failed", "执行失败"],
  ] as const)(
    "keeps the %s state explicit in the collapsed line",
    (eventType, kind, status, label) => {
      const state = runActivitySchema.parse({
        ...activity,
        status,
        items: [
          ...activity.items,
          {
            id: `state-${status}`,
            event_type: eventType,
            kind,
            status,
            title: label,
            timestamp: "2026-07-14T00:00:07Z",
            sequence: 7,
            metadata:
              eventType === "approval.requested"
                ? { approval_id: "approval-1", tool_call_id: "tool-1" }
                : {},
          },
        ],
      });
      const html = renderToStaticMarkup(<ActivitySummary activity={state} />);
      const phase =
        eventType === "approval.requested" ? "waiting_approval" : "failed";

      expect(html).toContain(label);
      expect(html).not.toContain(
        `<details class="execution-ribbon phase-${phase}" open`,
      );
    },
  );

  it("marks successful runs as a visually secondary state", () => {
    const completed = runActivitySchema.parse({
      ...activity,
      status: "succeeded",
      items: [
        ...activity.items,
        {
          id: "run-completed",
          event_type: "run.succeeded",
          kind: "result",
          status: "succeeded",
          title: "任务已完成",
          timestamp: "2026-07-14T00:00:07Z",
          sequence: 7,
          metadata: {},
        },
      ],
    });
    const html = renderToStaticMarkup(<ActivitySummary activity={completed} />);

    expect(html).toContain("phase-completed");
    expect(html).toContain("执行完成");
  });
});
