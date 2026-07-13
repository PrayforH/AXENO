"use client";

import type { ActivityItem, RunActivity } from "../lib/activity-schema";
import { useRunActivity } from "../lib/activity-store";

const statusLabels: Record<string, string> = {
  queued: "排队中",
  running: "运行中",
  waiting: "等待中",
  succeeded: "已完成",
  failed: "失败",
  cancelled: "已停止",
};

function visibleItems(items: ActivityItem[]): ActivityItem[] {
  return items.filter((item) => {
    if (item.event_type === "run.queued" || item.event_type === "message.completed") return false;
    if (item.event_type === "tool.result") {
      return !items.some(
        (candidate) =>
          candidate.event_type === "tool.request" &&
          candidate.metadata.tool_call_id === item.metadata.tool_call_id,
      );
    }
    return true;
  });
}

export function ActivitySummary({ activity }: { activity: RunActivity }) {
  const observed = useRunActivity();
  if (observed?.run_id === activity.run_id) activity = observed;
  const items = visibleItems(activity.items);
  const latest = items.slice(-4);
  const modelItem = [...items].reverse().find((item) => item.event_type === "model.route.selected");
  const toolCount = items.filter((item) => item.event_type === "tool.request" && item.kind === "tool").length;
  const subagentCount = items.filter((item) => item.kind === "subagent").length;

  return (
    <section className={`activity-summary activity-${activity.status}`} aria-label="执行进度">
      <header className="activity-summary-header">
        <div>
          <span className="activity-pulse" aria-hidden="true" />
          <strong>执行进度</strong>
          <span className="activity-status">{statusLabels[activity.status] ?? activity.status}</span>
        </div>
        <div className="activity-facts">
          {modelItem?.summary && <span>{modelItem.summary}</span>}
          {toolCount > 0 && <span>{toolCount} 个工具</span>}
          {subagentCount > 0 && <span>{subagentCount} 个子 Agent 事件</span>}
        </div>
      </header>
      <div className="activity-spine">
        {latest.map((item) => (
          <div className={`activity-row activity-kind-${item.kind}`} key={item.id}>
            <span className="activity-node" aria-hidden="true" />
            <div>
              <span>{item.title}</span>
              {item.summary && <small>{item.summary}</small>}
              {item.kind === "tool" && typeof item.metadata.name === "string" && (
                <code>{item.metadata.name}</code>
              )}
            </div>
            <span className={`activity-row-status status-${item.status}`}>
              {statusLabels[item.status] ?? item.status}
            </span>
          </div>
        ))}
      </div>
    </section>
  );
}
