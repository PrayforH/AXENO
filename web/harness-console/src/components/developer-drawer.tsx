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
  "runtime.system",
]);

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
  const notableItems = activity ? notableActivityItems(activity.items) : [];
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
          <span className="inspector-title-mark" aria-hidden="true"><i /><i /><i /></span>
          <div>
            <h2>本次运行</h2>
            <p>状态摘要与外部观测</p>
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
              <div><small>当前状态</small><strong>{statusLabels[activity.status] ?? activity.status}</strong></div>
              <span className="run-overview-duration">{overview.duration}</span>
            </div>
            <dl className="run-metrics">
              <div><dt>模型</dt><dd title={overview.model}>{overview.model}</dd></div>
              <div><dt>服务</dt><dd>{overview.provider}</dd></div>
              <div><dt>轮次</dt><dd>{overview.turns}</dd></div>
              <div><dt>费用</dt><dd>{overview.cost}</dd></div>
            </dl>
            <div className="run-counts">
              <span><strong>{overview.toolCalls}</strong> 工具调用</span>
              <span><strong>{overview.subagents}</strong> 子 Agent</span>
              <span>{overview.stopReason === "—" ? "执行中" : overview.stopReason}</span>
            </div>
          </section>

          <section className="observability-panel" aria-label="外部观测">
            <div className="inspector-section-title"><span>外部观测</span><span>Langfuse</span></div>
            <a
              className="observability-link"
              href={`/api/harness/observability?run_id=${encodeURIComponent(activity.run_id)}`}
              target="_blank"
              rel="noreferrer"
            >
              <span className="observability-mark" aria-hidden="true"><i /></span>
              <span>
                <strong>在 Langfuse 中查看</strong>
                <small>Trace、Span、模型指标与错误诊断</small>
              </span>
              <span className="external-arrow" aria-hidden="true">↗</span>
            </a>
          </section>

          <details className="inspector-activity">
            <summary>
              <span>已记录 {activity.items.length} 条活动</span>
              <small>{notableItems.length} 条关键记录</small>
              <span className="inspector-disclosure-chevron" aria-hidden="true" />
            </summary>
            <div className="inspector-timeline" aria-label="关键执行记录">
              {notableItems.map((item) => (
                <article className={`inspector-event inspector-kind-${item.kind}`} key={item.id}>
                  <div className="inspector-event-summary">
                    <span className="inspector-node" aria-hidden="true" />
                    <span className="inspector-event-copy">
                      <small>{kindLabels[item.kind] ?? "步骤"} · {item.sequence}</small>
                      <strong>{item.title}</strong>
                      {item.summary && <span>{item.summary}</span>}
                    </span>
                    <time>{new Date(item.timestamp).toLocaleTimeString("zh-CN", { hour12: false })}</time>
                  </div>
                </article>
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
          <span className="empty-orbit" aria-hidden="true" />
          <strong>还没有运行记录</strong>
          <p>提交任务后，可在这里查看运行摘要并跳转到外部 Trace。</p>
        </div>
      )}
    </aside>
  );
}
