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
      metadata: {
        task_id: "task-a",
        parent_tool_use_id: "root",
        alias: "fact-checker",
        agent_version: "1.0.0",
      },
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
      metadata: {
        task_id: "task-a",
        parent_tool_use_id: "root",
        alias: "fact-checker",
        agent_version: "1.0.0",
        duration_ms: 1000,
        usage: { tool_uses: 2 },
      },
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
      metadata: {
        task_id: "task-b",
        parent_tool_use_id: "root",
        alias: "risk-reviewer",
        agent_version: "1.0.0",
      },
    },
    {
      id: "tool-one",
      event_type: "tool.request",
      kind: "tool",
      status: "running",
      title: "调用 Read",
      timestamp: "2026-07-14T00:00:05Z",
      sequence: 5,
      metadata: {
        tool_call_id: "tool-1",
        name: "Read",
        arguments: { file_path: "docs/agent-production-platform-design.md" },
      },
    },
    {
      id: "tool-two",
      event_type: "tool.request",
      kind: "tool",
      status: "running",
      title: "调用 Grep",
      timestamp: "2026-07-14T00:00:06Z",
      sequence: 6,
      metadata: {
        tool_call_id: "tool-2",
        name: "Grep",
        arguments: {
          pattern: "publishDraft|promote",
          path: "web/harness-console",
        },
      },
    },
  ],
});

describe("execution ribbon", () => {
  it("expands active work before the assistant starts responding", () => {
    const html = renderToStaticMarkup(<ActivitySummary activity={activity} />);

    expect(html).toContain(
      '<details class="execution-ribbon phase-running" aria-label="执行进度 run-ribbon" data-run-id="run-ribbon" data-response-started="false" open="">',
    );
    expect(html).toContain("正在处理");
    expect(html).toContain('class="execution-state-mark"');
    expect(html).toContain("2 个工具");
    expect(html).toContain("2 个子任务");
    expect(html).toContain("6s");
  });

  it("collapses active work when the first real response text arrives", () => {
    const html = renderToStaticMarkup(
      <ActivitySummary activity={activity} responseStarted />,
    );

    expect(html).toContain('<details class="execution-ribbon phase-running"');
    expect(html).not.toContain(
      '<details class="execution-ribbon phase-running" aria-label="执行进度 run-ribbon" data-run-id="run-ribbon" open',
    );
    expect(html).toContain('aria-expanded="false"');
  });

  it("does not collapse a completed run before its response is mounted", () => {
    const completed = runActivitySchema.parse({
      ...activity,
      status: "succeeded",
    });
    const waitingForResponse = renderToStaticMarkup(
      <ActivitySummary activity={completed} />,
    );
    const responseMounted = renderToStaticMarkup(
      <ActivitySummary activity={completed} responseStarted />,
    );

    expect(waitingForResponse).toContain('data-response-started="false" open');
    expect(responseMounted).toContain('data-response-started="true"');
    expect(responseMounted).not.toContain('data-response-started="true" open');
  });

  it("interleaves visible model commentary with actions but excludes the final answer", () => {
    const narrated = runActivitySchema.parse({
      ...activity,
      items: [
        activity.items[0],
        {
          id: "commentary-before-read",
          event_type: "message.delta",
          kind: "analysis",
          status: "succeeded",
          title: "进展说明",
          summary: "我先读取设计文档，再检查发布边界。",
          timestamp: "2026-07-14T00:00:02Z",
          sequence: 2,
          metadata: { message_id: "assistant-progress" },
        },
        ...activity.items.slice(1).map((item) => ({
          ...item,
          sequence: item.sequence + 1,
        })),
        {
          id: "final-answer",
          event_type: "message.delta",
          kind: "analysis",
          status: "succeeded",
          title: "进展说明",
          summary: "最终结论已经整理完成。",
          timestamp: "2026-07-14T00:00:08Z",
          sequence: 8,
          metadata: { message_id: "assistant-final" },
        },
      ],
    });
    const html = renderToStaticMarkup(<ActivitySummary activity={narrated} />);

    expect(html).toContain("我先读取设计文档，再检查发布边界。");
    expect(html).not.toContain("最终结论已经整理完成。");
    expect(html.indexOf("我先读取设计文档")).toBeLessThan(
      html.indexOf("正在读取 docs/agent-production-platform-design.md"),
    );
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
    expect(html).toContain("fact-checker");
    expect(html).toContain("risk-reviewer");
    expect(html).toContain("fact-checker@1.0.0");
    expect(html).toContain("2 个工具");
    expect(html).toContain("正在读取 docs/agent-production-platform-design.md");
    expect(html).toContain(
      "正在 web/harness-console 中搜索“publishDraft|promote”",
    );
    expect(html).not.toContain("subagent.started");
  });

  it("uses active wording for a tool that has not produced a result", () => {
    const html = renderToStaticMarkup(<ActivitySummary activity={activity} />);

    expect(html).toContain("正在读取 docs/agent-production-platform-design.md");
    expect(html).not.toContain("已读取 docs/agent-production-platform-design.md");
    expect(html).toContain("进行中");
  });

  it("uses one chronological work log for expanded run details", () => {
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

    expect(html).toContain('aria-label="思考与行动"');
    expect(html).toContain("运行模型");
    expect(html).not.toContain("<h4>子任务</h4>");
    expect(html).not.toContain("<h4>使用的工具</h4>");
  });

  it("shows completed discovery tools directly inside the turn disclosure", () => {
    const completedTools = runActivitySchema.parse({
      ...activity,
      items: [
        ...activity.items,
        {
          id: "tool-one-result",
          event_type: "tool.result",
          kind: "tool",
          status: "succeeded",
          title: "Read 已完成",
          timestamp: "2026-07-14T00:00:07Z",
          sequence: 7,
          metadata: { tool_call_id: "tool-1" },
        },
        {
          id: "tool-two-result",
          event_type: "tool.result",
          kind: "tool",
          status: "succeeded",
          title: "Grep 已完成",
          timestamp: "2026-07-14T00:00:08Z",
          sequence: 8,
          metadata: { tool_call_id: "tool-2" },
        },
        {
          id: "tool-three",
          event_type: "tool.request",
          kind: "tool",
          status: "running",
          title: "调用 Glob",
          timestamp: "2026-07-14T00:00:09Z",
          sequence: 9,
          metadata: {
            tool_call_id: "tool-3",
            name: "Glob",
            arguments: { pattern: "src/**/*.py", path: "src/harness" },
          },
        },
        {
          id: "tool-three-result",
          event_type: "tool.result",
          kind: "tool",
          status: "succeeded",
          title: "Glob 已完成",
          timestamp: "2026-07-14T00:00:10Z",
          sequence: 10,
          metadata: { tool_call_id: "tool-3" },
        },
        {
          id: "run-completed",
          event_type: "run.succeeded",
          kind: "result",
          status: "succeeded",
          title: "任务已完成",
          timestamp: "2026-07-14T00:00:11Z",
          sequence: 11,
          metadata: {},
        },
      ],
    });

    const html = renderToStaticMarkup(<ActivitySummary activity={completedTools} />);

    expect(html).toContain('data-run-id="run-ribbon"');
    expect(html).toContain("已读取文件");
    expect(html).not.toContain('class="execution-tool-batch"');
    expect(html).toContain("已查找文件 src/**/*.py，范围 src/harness");
    expect(html).toContain("已读取 docs/agent-production-platform-design.md");
    expect(html).toContain(
      "已在 web/harness-console 中搜索“publishDraft|promote”",
    );
  });

  it("keeps each completed run in its own Codex-style turn group", () => {
    const first = runActivitySchema.parse({
      ...activity,
      run_id: "run-first",
      status: "succeeded",
      items: [
        ...activity.items,
        {
          id: "first-result",
          event_type: "tool.result",
          kind: "tool",
          status: "succeeded",
          title: "Read 已完成",
          timestamp: "2026-07-14T00:00:07Z",
          sequence: 7,
          metadata: { tool_call_id: "tool-1" },
        },
        {
          id: "first-completed",
          event_type: "run.succeeded",
          kind: "result",
          status: "succeeded",
          title: "任务已完成",
          timestamp: "2026-07-14T00:00:08Z",
          sequence: 8,
          metadata: {},
        },
      ],
    });
    const second = runActivitySchema.parse({
      run_id: "run-second",
      status: "succeeded",
      started_at: "2026-07-14T00:01:00Z",
      metrics: {},
      items: [
        {
          id: "second-tool",
          event_type: "tool.request",
          kind: "tool",
          status: "running",
          title: "调用 Bash",
          timestamp: "2026-07-14T00:01:01Z",
          sequence: 1,
          metadata: {
            tool_call_id: "tool-second",
            name: "Bash",
            arguments: { command: "npm test" },
          },
        },
        {
          id: "second-result",
          event_type: "tool.result",
          kind: "tool",
          status: "succeeded",
          title: "Bash 已完成",
          timestamp: "2026-07-14T00:01:02Z",
          sequence: 2,
          metadata: { tool_call_id: "tool-second" },
        },
        {
          id: "second-completed",
          event_type: "run.succeeded",
          kind: "result",
          status: "succeeded",
          title: "任务已完成",
          timestamp: "2026-07-14T00:01:03Z",
          sequence: 3,
          metadata: {},
        },
      ],
    });

    const html = renderToStaticMarkup(
      <>{[first, second].map((item) => (
        <ActivitySummary activity={item} key={item.run_id} />
      ))}</>,
    );

    expect(html).toContain('data-run-id="run-first"');
    expect(html).toContain('data-run-id="run-second"');
    expect(html).toContain("已读取文件");
    expect(html).toContain("已运行命令");
    expect(html).toContain("已运行 npm test");
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
      if (phase === "waiting_approval") {
        expect(html).toContain(
          `<details class="execution-ribbon phase-${phase}" aria-label="执行进度 run-ribbon" data-run-id="run-ribbon" data-response-started="false" open`,
        );
      } else {
        expect(html).not.toContain(
          `<details class="execution-ribbon phase-${phase}" aria-label="执行进度 run-ribbon" data-run-id="run-ribbon" open`,
        );
      }
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
    expect(html).toContain("已读取文件");
  });
});
