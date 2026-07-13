"use client";

import { CopilotKitInspector } from "@copilotkit/react-core/v2";
import { activityOverview } from "../lib/activity-schema";
import { useRunActivity } from "../lib/activity-store";
import { developerRows } from "../lib/developer-details";
import { StructuredValue } from "./structured-value";

const statusLabels: Record<string, string> = {
  queued: "排队中",
  running: "运行中",
  waiting: "等待中",
  succeeded: "已完成",
  failed: "失败",
  cancelled: "已停止",
};

const kindLabels: Record<string, string> = {
  run: "RUN",
  analysis: "WORK",
  tool: "TOOL",
  subagent: "AGENT",
  artifact: "FILE",
  result: "DONE",
  error: "ERROR",
};

export function DeveloperDrawer({
  threadId,
  onClose,
}: {
  threadId: string;
  onClose?: () => void;
}) {
  const activity = useRunActivity();
  const overview = activity ? activityOverview(activity) : undefined;

  return (
    <aside className="developer-drawer" aria-label="运行详情">
      <header className="inspector-header">
        <div>
          <p className="eyebrow">Run inspector</p>
          <h2>运行详情</h2>
        </div>
        {onClose && (
          <button type="button" className="inspector-close" onClick={onClose} aria-label="关闭运行详情">×</button>
        )}
      </header>

      {activity && overview ? (
        <>
          <section className="run-overview">
            <div className="run-overview-status">
              <span className={`activity-pulse status-${activity.status}`} aria-hidden="true" />
              <div><small>RUN STATUS</small><strong>{statusLabels[activity.status] ?? activity.status}</strong></div>
              <code>{activity.run_id.slice(0, 8)}</code>
            </div>
            <dl className="run-metrics">
              <div><dt>MODEL</dt><dd title={overview.model}>{overview.model}</dd></div>
              <div><dt>PROVIDER</dt><dd>{overview.provider}</dd></div>
              <div><dt>DURATION</dt><dd>{overview.duration}</dd></div>
              <div><dt>TURNS</dt><dd>{overview.turns}</dd></div>
              <div><dt>COST</dt><dd>{overview.cost}</dd></div>
              <div><dt>STOP</dt><dd>{overview.stopReason}</dd></div>
            </dl>
            <div className="run-counts">
              <span><strong>{overview.toolCalls}</strong> 工具调用</span>
              <span><strong>{overview.subagents}</strong> 子 Agent</span>
            </div>
          </section>

          <section className="inspector-timeline" aria-label="完整执行时间线">
            <div className="inspector-section-title"><span>完整时间线</span><code>{activity.items.length} EVENTS</code></div>
            {activity.items.map((item) => (
              <details className={`inspector-event inspector-kind-${item.kind}`} key={item.id}>
                <summary>
                  <span className="inspector-node" aria-hidden="true" />
                  <span className="inspector-event-copy">
                    <small>{kindLabels[item.kind] ?? item.kind.toUpperCase()} · {item.sequence}</small>
                    <strong>{item.title}</strong>
                    {item.summary && <span>{item.summary}</span>}
                  </span>
                  <time>{new Date(item.timestamp).toLocaleTimeString("zh-CN", { hour12: false })}</time>
                </summary>
                {Object.keys(item.metadata).length > 0 && (
                  <div className="inspector-event-detail">
                    <StructuredValue value={item.metadata} label="事件数据" />
                  </div>
                )}
              </details>
            ))}
          </section>
        </>
      ) : (
        <div className="inspector-empty">
          <span className="empty-orbit" aria-hidden="true" />
          <strong>等待 Agent 运行</strong>
          <p>发送消息后，这里会显示工作摘要、工具调用、子 Agent 与模型指标。</p>
        </div>
      )}

      <details className="raw-inspector">
        <summary>协议与原始事件</summary>
        <div className="developer-grid">
          {developerRows(threadId).map(([label, value]) => (
            <div className="developer-row" key={label}><span>{label}</span><code>{value}</code></div>
          ))}
        </div>
        <CopilotKitInspector />
      </details>
    </aside>
  );
}
