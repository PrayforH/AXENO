import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { ActivitySummary } from "../src/components/activity-summary";
import { ApprovalCard } from "../src/components/approval-card";
import { ArtifactCard } from "../src/components/artifact-list";
import { SubagentCard } from "../src/components/subagent-card";
import { ToolCard } from "../src/components/tool-card";
import { UploadFeedbackContent } from "../src/components/agent-thread";
import {
  activityOverview,
  latestRunActivity,
  runActivitySchema,
} from "../src/lib/activity-schema";

const activity = {
  run_id: "run-1",
  status: "running",
  started_at: "2026-07-13T01:00:00Z",
  metrics: {},
  items: [
    {
      id: "event-1",
      event_type: "model.route.selected",
      kind: "run",
      status: "succeeded",
      title: "模型路由已选择",
      summary: "claude-sonnet",
      timestamp: "2026-07-13T01:00:01Z",
      sequence: 1,
      metadata: { provider: "new-api", model: "claude-sonnet" },
    },
    {
      id: "event-2",
      event_type: "tool.request",
      kind: "tool",
      status: "running",
      title: "调用 Read",
      timestamp: "2026-07-13T01:00:02Z",
      sequence: 2,
      metadata: { name: "Read" },
    },
    {
      id: "event-3",
      event_type: "subagent.started",
      kind: "subagent",
      status: "running",
      title: "子 Agent 正在执行",
      summary: "分析仓库",
      timestamp: "2026-07-13T01:00:03Z",
      sequence: 3,
      metadata: { task_id: "task-1" },
    },
  ],
};

describe("Codex-style activity UI", () => {
  it("validates the durable activity payload", () => {
    expect(runActivitySchema.parse(activity).items).toHaveLength(3);
  });

  it("finds the latest activity and derives inspector facts", () => {
    const completed = runActivitySchema.parse({
      ...activity,
      status: "succeeded",
      metrics: { turns: 3, cost_usd: 0.0125, stop_reason: "end_turn" },
    });
    const found = latestRunActivity([
      { role: "user", content: "hello" },
      { role: "activity", activityType: "harness.run.v1", content: completed },
    ]);
    expect(found?.run_id).toBe("run-1");
    expect(activityOverview(completed)).toMatchObject({
      model: "claude-sonnet",
      provider: "new-api",
      turns: "3",
      cost: "$0.0125",
      stopReason: "end_turn",
    });
  });

  it("summarizes model, tools, and subagents without raw event JSON", () => {
    const html = renderToStaticMarkup(
      <ActivitySummary activity={runActivitySchema.parse(activity)} />,
    );
    expect(html).toContain("执行进度");
    expect(html).toContain("Read");
    expect(html).toContain("子任务");
    expect(html).toContain("使用的工具");
    expect(html).toContain("运行模型");
    expect(html).toContain("claude-sonnet");
    expect(html).not.toContain("model.route.selected");
  });

  it("renders rich tool input and result cards", () => {
    const html = renderToStaticMarkup(
      <ToolCard name="Read" status="complete" args={{ file_path: "README.md" }} result={'{"ok":true}'} />,
    );
    expect(html).toContain("Read");
    expect(html).toContain("已完成");
    expect(html).toContain("file_path");
    expect(html).toContain("json-boolean");
  });

  it("presents Task calls as delegated subagents", () => {
    const html = renderToStaticMarkup(
      <SubagentCard
        status="executing"
        parameters={{ description: "分析仓库", subagent_type: "helper" }}
      />,
    );
    expect(html).toContain("子 Agent");
    expect(html).toContain("helper");
    expect(html).toContain("分析仓库");
  });

  it("renders upload progress and actionable errors", () => {
    const html = renderToStaticMarkup(
      <UploadFeedbackContent
        items={[
          { key: "a", fileName: "facts.txt", status: "uploading" },
          { key: "b", fileName: "report.docx", status: "error", message: "too large" },
        ]}
        onDismiss={() => undefined}
      />,
    );
    expect(html).toContain("正在上传");
    expect(html).toContain("上传失败：too large");
    expect(html).toContain("关闭 report.docx 上传错误");
  });

  it("renders authenticated preview and download actions for artifacts", () => {
    const html = renderToStaticMarkup(
      <ArtifactCard
        details={{
          artifact_id: "artifact-1",
          run_id: "run-1",
          name: "report.pdf",
          media_type: "application/pdf",
          size_bytes: 2048,
        }}
      />,
    );
    expect(html).toContain("PDF");
    expect(html).toContain("预览");
    expect(html).toContain("?preview=1");
    expect(html).toContain("下载");
  });

  it("renders actionable controls for a pending inline approval", () => {
    const html = renderToStaticMarkup(
      <ApprovalCard
        details={{
          approval_id: "approval-1",
          run_id: "run-1",
          tool_call_id: "tool-1",
          reason: "matched policy rule write-review",
        }}
        complete={false}
        onDecision={async () => undefined}
      />,
    );

    expect(html).toContain("允许 Agent 执行受保护操作？");
    expect(html).toContain("批准并继续");
    expect(html).toContain("拒绝");
    expect(html).toContain("write-review");
  });
});
