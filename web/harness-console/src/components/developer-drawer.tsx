"use client";

import { useEffect, useRef, useState } from "react";
import { activityOverview, type ActivityItem } from "../lib/activity-schema";
import { useRunActivity } from "../lib/activity-store";
import { isHiddenByCollapsedDetails } from "../lib/focus-target";

const statusLabels: Record<string, string> = {
  queued: "排队中",
  running: "运行中",
  waiting: "等待中",
  succeeded: "已完成",
  failed: "失败",
  cancelled: "已停止",
  rejected: "已拒绝",
  timed_out: "已超时",
};

const kindLabels: Record<string, string> = {
  run: "运行",
  analysis: "分析",
  tool: "工具",
  subagent: "子任务",
  artifact: "文件",
  result: "完成",
  error: "错误",
};

const noisyEventTypes = new Set([
  "message.delta",
  "subagent.delta",
  "subagent.progress",
  "subagent.updated",
  "runtime.system",
  "message.start",
  "message.completed",
]);

interface TraceEntry {
  id: string;
  kind: ActivityItem["kind"];
  status: string;
  title: string;
  summary?: string;
  sequence: number;
  timestamp: string;
  durationMs?: number;
  input?: string;
  output?: string;
  artifact?: {
    id: string;
    name: string;
    mediaType?: string;
    sizeBytes?: number;
  };
}

function traceDuration(start: string, end: string) {
  const duration = Date.parse(end) - Date.parse(start);
  return Number.isFinite(duration) && duration >= 0 ? duration : undefined;
}

function traceDurationLabel(durationMs?: number) {
  if (durationMs === undefined) return undefined;
  if (durationMs < 1_000) return `${durationMs}ms`;
  return `${(durationMs / 1_000).toFixed(durationMs < 10_000 ? 1 : 0)}s`;
}

function traceToolTitle(name: string, argumentsValue: Record<string, unknown>) {
  const description = argumentsValue.description;
  if (typeof description === "string" && description.trim()) return description.trim();
  const labels: Record<string, string> = {
    Bash: "运行命令",
    Glob: "查找文件",
    Grep: "搜索内容",
    Read: "读取文件",
    Write: "写入文件",
    Edit: "编辑文件",
    Task: "委派子任务",
    Agent: "委派子任务",
  };
  return labels[name] ?? `调用 ${name}`;
}

function traceToolInput(name: string, argumentsValue: Record<string, unknown>) {
  if (name === "Bash" && typeof argumentsValue.command === "string") {
    return argumentsValue.command;
  }
  return JSON.stringify(argumentsValue, null, 2);
}

/** Build a compact audit trace while keeping each tool input and result inspectable. */
export function traceActivityEntries(items: readonly ActivityItem[]): TraceEntry[] {
  const results = new Map<string, ActivityItem>();
  const approvals = new Map<string, ActivityItem>();
  const messageGroups = new Map<string, TraceEntry>();

  for (const item of items) {
    const toolCallId = item.metadata.tool_call_id;
    if (typeof toolCallId !== "string") continue;
    if (item.event_type === "tool.result" || item.event_type === "tool.allowed") {
      results.set(toolCallId, item);
    } else if (item.event_type === "approval.requested") {
      approvals.set(toolCallId, item);
    }
  }

  const entries: TraceEntry[] = [];
  for (const item of items) {
    if (item.event_type === "message.delta") {
      if (!item.summary?.trim()) continue;
      const rawMessageId = item.metadata.message_id;
      const messageId = typeof rawMessageId === "string" ? rawMessageId : "model-progress";
      const existing = messageGroups.get(messageId);
      if (existing) {
        existing.output = `${existing.output ?? ""}${item.summary}`;
        existing.durationMs = traceDuration(existing.timestamp, item.timestamp);
      } else {
        const entry: TraceEntry = {
          id: `message-${messageId}`,
          kind: "analysis",
          status: "succeeded",
          title: "模型进展说明",
          sequence: item.sequence,
          timestamp: item.timestamp,
          output: item.summary,
        };
        messageGroups.set(messageId, entry);
        entries.push(entry);
      }
      continue;
    }

    if (noisyEventTypes.has(item.event_type)) continue;
    if (
      item.event_type === "tool.result" ||
      item.event_type === "tool.allowed" ||
      item.event_type === "approval.requested"
    ) continue;

    if (item.event_type === "tool.request") {
      const name = typeof item.metadata.name === "string" ? item.metadata.name : "工具";
      const rawArguments = item.metadata.arguments;
      const argumentsValue =
        rawArguments && typeof rawArguments === "object" && !Array.isArray(rawArguments)
          ? rawArguments as Record<string, unknown>
          : {};
      const toolCallId =
        typeof item.metadata.tool_call_id === "string" ? item.metadata.tool_call_id : item.id;
      const result = results.get(toolCallId);
      const approval = approvals.get(toolCallId);
      const resultSummary = result?.metadata.result_summary;
      const resultPreview = result?.metadata.result_preview;
      entries.push({
        id: `trace-${toolCallId}`,
        kind: item.kind,
        status: result?.status ?? approval?.status ?? item.status,
        title: traceToolTitle(name, argumentsValue),
        summary:
          typeof resultSummary === "string"
            ? resultSummary
            : approval?.summary ?? item.summary ?? undefined,
        sequence: item.sequence,
        timestamp: item.timestamp,
        durationMs: result ? traceDuration(item.timestamp, result.timestamp) : undefined,
        input: traceToolInput(name, argumentsValue),
        output: typeof resultPreview === "string" ? resultPreview : undefined,
      });
      continue;
    }

    if (item.event_type === "artifact.ready") {
      const artifactId = item.metadata.artifact_id;
      if (typeof artifactId === "string") {
        const sourcePath =
          typeof item.metadata.source_path === "string"
            ? item.metadata.source_path
            : undefined;
        entries.push({
          id: item.id,
          kind: item.kind,
          status: item.status,
          title: "生成运行产物",
          summary: sourcePath ?? item.summary ?? undefined,
          sequence: item.sequence,
          timestamp: item.timestamp,
          artifact: {
            id: artifactId,
            name: sourcePath ?? item.summary ?? "未命名产物",
            mediaType:
              typeof item.metadata.media_type === "string"
                ? item.metadata.media_type
                : undefined,
            sizeBytes:
              typeof item.metadata.size_bytes === "number"
                ? item.metadata.size_bytes
                : undefined,
          },
        });
        continue;
      }
    }

    entries.push({
      id: item.id,
      kind: item.kind,
      status: item.status,
      title: item.title,
      summary: item.summary ?? undefined,
      sequence: item.sequence,
      timestamp: item.timestamp,
    });
  }
  return entries.sort((left, right) => left.sequence - right.sequence);
}

function traceStatusLabel(status: string) {
  if (["succeeded", "completed"].includes(status)) return "成功";
  if (["failed", "rejected", "timed_out"].includes(status)) return "失败";
  if (status === "waiting") return "待审批";
  if (status === "cancelled") return "已停止";
  return "运行中";
}

function traceBytes(value?: number) {
  if (value === undefined) return undefined;
  if (value < 1_024) return `${value} B`;
  return `${(value / 1_024).toFixed(1)} KB`;
}

export function notableActivityItems(items: readonly ActivityItem[]) {
  return items
    .filter((item) => {
      if (noisyEventTypes.has(item.event_type)) return false;
      if (
        item.kind === "tool" &&
        ["succeeded", "completed", "running"].includes(item.status)
      ) return false;
      return true;
    })
    .slice(-12);
}

function useNarrowRunPanel() {
  const [isModal, setIsModal] = useState(false);

  useEffect(() => {
    const query = window.matchMedia("(max-width: 980px)");
    const update = () => setIsModal(query.matches);
    update();
    query.addEventListener("change", update);
    return () => query.removeEventListener("change", update);
  }, []);

  return isModal;
}

export function DeveloperDrawer({
  threadId,
  onClose,
}: {
  threadId: string;
  onClose?: () => void;
}) {
  const activity = useRunActivity();
  const overview = activity ? activityOverview(activity) : undefined;
  const isModal = useNarrowRunPanel();
  const traceEntries = activity ? traceActivityEntries(activity.items) : [];
  const panelRef = useRef<HTMLElement>(null);
  const closeButtonRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (!isModal) return;
    const panel = panelRef.current;
    const previouslyFocused =
      document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const backgroundState = Array.from(
      document.querySelectorAll<HTMLElement>(".console-header, .chat-stage"),
      (background) => [background, background.inert] as const,
    );
    for (const [background] of backgroundState) background.inert = true;
    closeButtonRef.current?.focus();

    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") {
        event.preventDefault();
        onClose?.();
        return;
      }
      if (event.key !== "Tab" || !panel) return;
      const focusable = Array.from(
        panel.querySelectorAll<HTMLElement>(
          'button:not([disabled]), a[href], input:not([disabled]), textarea:not([disabled]), select:not([disabled]), summary, [tabindex]:not([tabindex="-1"])',
        ),
      ).filter((element) => {
        if (
          element.hidden ||
          element.inert ||
          element.closest('[hidden], [inert], [aria-hidden="true"]') ||
          isHiddenByCollapsedDetails(element)
        ) return false;
        const style = window.getComputedStyle(element);
        return (
          style.display !== "none" &&
          style.visibility !== "hidden" &&
          element.getClientRects().length > 0
        );
      });
      if (focusable.length === 0) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      const active = document.activeElement;
      if (event.shiftKey && (active === first || !panel.contains(active))) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && (active === last || !panel.contains(active))) {
        event.preventDefault();
        first.focus();
      }
    }

    document.addEventListener("keydown", handleKeyDown);
    return () => {
      document.removeEventListener("keydown", handleKeyDown);
      for (const [background, wasInert] of backgroundState) {
        background.inert = wasInert;
      }
      previouslyFocused?.focus();
    };
  }, [isModal, onClose]);

  return (
    <aside
      ref={panelRef}
      className="developer-drawer"
      aria-label="运行详情"
      role={isModal ? "dialog" : undefined}
      aria-modal={isModal || undefined}
    >
      <header className="inspector-header">
        <div className="inspector-title">
          <div>
            <p>本次运行</p>
            <h2>运行详情</h2>
          </div>
        </div>
        {onClose && (
          <button ref={closeButtonRef} type="button" className="inspector-close" onClick={onClose} aria-label="关闭运行详情"><span aria-hidden="true" /></button>
        )}
      </header>

      {activity && overview ? (
        <>
          <section className="run-overview">
            <div className="run-overview-status">
              <span className={`activity-pulse status-${activity.status}`} aria-hidden="true" />
              <div><strong>{statusLabels[activity.status] ?? activity.status}</strong><small>本次运行</small></div>
              <span className="run-overview-duration">{overview.duration}</span>
            </div>
            <dl className="run-metrics">
              <div className="run-metric-wide"><dt>模型</dt><dd title={overview.model}>{overview.model}</dd></div>
              <div><dt>服务</dt><dd>{overview.provider}</dd></div>
              <div><dt>轮次</dt><dd>{overview.turns}</dd></div>
              <div><dt>费用</dt><dd>{overview.cost}</dd></div>
              <div><dt>耗时</dt><dd>{overview.duration}</dd></div>
            </dl>
            <div className="run-counts">
              <span><strong>{overview.toolCalls}</strong> 工具</span>
              <span><strong>{overview.subagents}</strong> 子任务</span>
              <span>结束原因 <strong>{overview.stopReason === "—" ? "执行中" : overview.stopReason}</strong></span>
            </div>
          </section>

          <section className="observability-panel" aria-label="外部观测">
            <div className="inspector-section-title"><span>可观测性</span><span>Langfuse</span></div>
            {activity.trace_id ? (
              <a
                className="observability-link"
                href={`/api/harness/observability?run_id=${encodeURIComponent(activity.run_id)}&trace_id=${encodeURIComponent(activity.trace_id)}`}
                target="_blank"
                rel="noreferrer"
              >
                <span>
                  <strong>打开 Trace</strong>
                  <small title={activity.trace_id}>{activity.trace_id.slice(0, 12)}…</small>
                </span>
                <span className="external-arrow" aria-hidden="true">↗</span>
              </a>
            ) : (
              <div className="observability-link is-disabled">
                <span>
                  <strong>Trace 尚未生成</strong>
                  <small>运行开始后会在这里提供直接链接</small>
                </span>
              </div>
            )}
          </section>

          <details className="inspector-activity inspector-trace" open>
            <summary>
              <span>Trace · {traceEntries.length} 个步骤</span>
              <small>{activity.items.length} 条原始事件</small>
              <span className="inspector-disclosure-chevron" aria-hidden="true" />
            </summary>
            <div className="trace-ledger" aria-label="完整执行 Trace">
              {traceEntries.map((entry, index) => (
                <details
                  className={`trace-step trace-kind-${entry.kind} trace-status-${entry.status}`}
                  key={entry.id}
                  open={entry.status === "failed"}
                >
                  <summary>
                    <span className="trace-index" aria-hidden="true">{String(index + 1).padStart(2, "0")}</span>
                    <span className="trace-step-copy">
                      <span className="trace-step-title">{entry.title}</span>
                      <span className="trace-step-meta">
                        {kindLabels[entry.kind] ?? "步骤"}
                        {entry.summary ? ` · ${entry.summary}` : ""}
                      </span>
                    </span>
                    <span className="trace-step-facts">
                      {traceDurationLabel(entry.durationMs) && <time>{traceDurationLabel(entry.durationMs)}</time>}
                      <span>{traceStatusLabel(entry.status)}</span>
                    </span>
                    <span className="trace-chevron" aria-hidden="true" />
                  </summary>
                  <div className="trace-step-detail">
                    <div className="trace-step-clock">
                      <span>事件 #{entry.sequence}</span>
                      <time>{new Date(entry.timestamp).toLocaleTimeString("zh-CN", { hour12: false })}</time>
                    </div>
                    {entry.input && (
                      <section>
                        <h3>输入</h3>
                        <pre>{entry.input}</pre>
                      </section>
                    )}
                    {entry.output && (
                      <section>
                        <h3>返回</h3>
                        <pre>{entry.output}</pre>
                      </section>
                    )}
                    {!entry.output && entry.summary && !entry.artifact && (
                      <section>
                        <h3>结果</h3>
                        <p>{entry.summary}</p>
                      </section>
                    )}
                    {entry.artifact && (
                      <section className="trace-artifact">
                        <h3>可访问产物</h3>
                        <div>
                          <span>
                            <strong>{entry.artifact.name}</strong>
                            <small>
                              {[entry.artifact.mediaType, traceBytes(entry.artifact.sizeBytes)]
                                .filter(Boolean)
                                .join(" · ")}
                            </small>
                          </span>
                          <a
                            href={`/api/harness/artifacts/${encodeURIComponent(entry.artifact.id)}?preview=1`}
                            target="_blank"
                            rel="noreferrer"
                          >预览</a>
                          <a
                            href={`/api/harness/artifacts/${encodeURIComponent(entry.artifact.id)}`}
                            download={entry.artifact.name}
                          >下载</a>
                        </div>
                      </section>
                    )}
                  </div>
                </details>
              ))}
            </div>
          </details>

          <details className="run-identifiers">
            <summary>运行标识</summary>
            <dl>
              <div><dt>Run</dt><dd><code>{activity.run_id}</code></dd></div>
              <div><dt>Thread</dt><dd><code>{threadId}</code></dd></div>
            </dl>
          </details>
        </>
      ) : (
        <div className="inspector-empty">
          <strong>还没有运行记录</strong>
          <p>提交任务后，可在这里查看运行摘要并跳转到外部 Trace。</p>
        </div>
      )}
    </aside>
  );
}
