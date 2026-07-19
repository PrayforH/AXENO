"use client";

import { useEffect, useState, type MouseEvent } from "react";
import type { RunActivity } from "../lib/activity-schema";
import { useRunViewModel } from "../lib/activity-store";
import {
  reduceRunViewModel,
  type RunPhase,
  type RunTaskNode,
  type RunToolNode,
  type RunViewModel,
  type WorkStatus,
} from "../lib/run-view-model";
import {
  toolActivitySentence,
  toolBatchTitle,
} from "../lib/tool-presentation";

const phaseLabels: Record<RunPhase, string> = {
  queued: "等待处理",
  running: "正在处理",
  waiting_approval: "等待审批",
  completed: "已处理",
  failed: "处理失败",
  rejected: "已拒绝",
  cancelled: "已停止",
};

const workLabels: Record<WorkStatus, string> = {
  running: "进行中",
  waiting: "等待中",
  completed: "已完成",
  failed: "失败",
};

function durationLabel(elapsedMs: number) {
  if (elapsedMs < 1_000) return `${elapsedMs}ms`;
  if (elapsedMs < 60_000) return `${Math.round(elapsedMs / 1_000)}s`;
  const minutes = Math.floor(elapsedMs / 60_000);
  const seconds = Math.round((elapsedMs % 60_000) / 1_000);
  return `${minutes}m ${seconds}s`;
}

function TaskRow({ task }: { task: RunTaskNode }) {
  const active = task.status === "running" || task.status === "waiting";
  return (
    <details
      className={`execution-task task-${task.status}`}
      open={active}
    >
      <summary>
        <span className="execution-node" aria-hidden="true" />
        <span>
          {task.alias && <strong>{task.alias}</strong>}
          {task.alias && task.title !== task.alias ? <em>{task.title}</em> : task.title}
        </span>
        <small>{workLabels[task.status]}</small>
      </summary>
      <div className="execution-task-detail">
        <code>{task.agentVersion ? `${task.alias}@${task.agentVersion}` : task.id}</code>
        {task.parentId && <span>父任务 {task.parentId}</span>}
        {task.durationMs !== undefined && <span>{durationLabel(task.durationMs)}</span>}
        {task.tokens !== undefined && <span>{task.tokens.toLocaleString("zh-CN")} tokens</span>}
        {task.costUsd !== undefined && <span>${task.costUsd.toFixed(4)}</span>}
        {task.toolUses !== undefined && <span>{task.toolUses} 个工具</span>}
        {task.errorCode && <span className="execution-error-code">{task.errorCode}</span>}
      </div>
    </details>
  );
}

function ToolRow({ tool }: { tool: RunToolNode }) {
  return (
    <div className={`execution-tool tool-${tool.status}`}>
      <span className="execution-node" aria-hidden="true" />
      <span className="execution-tool-copy">
        <span className="execution-tool-heading">
          <strong>{toolActivitySentence(tool)}</strong>
        </span>
        {tool.resultSummary && (
          <span className="execution-tool-details">
            <em>{tool.resultSummary}</em>
          </span>
        )}
      </span>
      <small>{workLabels[tool.status]}</small>
    </div>
  );
}

interface CommentaryNode {
  id: string;
  text: string;
  sequence: number;
}

type TimelineNode =
  | { kind: "commentary"; sequence: number; commentary: CommentaryNode }
  | { kind: "task"; sequence: number; task: RunTaskNode }
  | { kind: "tool"; sequence: number; tool: RunToolNode };

function commentaryNodes(view: RunViewModel): CommentaryNode[] {
  const actionSequences = view.items
    .filter(
      (item) =>
        item.event_type === "tool.request" ||
        item.event_type === "subagent.started",
    )
    .map((item) => item.sequence)
    .sort((left, right) => left - right);
  const grouped = new Map<number, CommentaryNode>();

  for (const item of view.items) {
    if (item.event_type !== "message.delta" || !item.summary?.trim()) continue;
    const nextAction = actionSequences.find((sequence) => sequence > item.sequence);
    if (nextAction === undefined) continue;
    const existing = grouped.get(nextAction);
    grouped.set(nextAction, {
      id: existing?.id ?? item.id,
      sequence: existing?.sequence ?? item.sequence,
      text: `${existing?.text ?? ""}${item.summary}`,
    });
  }
  return [...grouped.values()];
}

function executionTimeline(view: RunViewModel): TimelineNode[] {
  return [
    ...commentaryNodes(view).map(
      (commentary): TimelineNode => ({
        kind: "commentary",
        sequence: commentary.sequence,
        commentary,
      }),
    ),
    ...view.tasks.map(
      (task): TimelineNode => ({ kind: "task", sequence: task.sequence, task }),
    ),
    ...view.tools.map(
      (tool): TimelineNode => ({ kind: "tool", sequence: tool.sequence, tool }),
    ),
  ].sort((left, right) => left.sequence - right.sequence);
}

function ribbonFacts(view: RunViewModel) {
  const facts: string[] = [];
  if (view.toolCount > 0) facts.push(`${view.toolCount} 个工具`);
  if (view.taskCount > 0) facts.push(`${view.taskCount} 个子任务`);
  if (view.totalTokens !== undefined) {
    facts.push(`${view.totalTokens.toLocaleString("zh-CN")} tokens`);
  }
  if (view.totalCostUsd !== undefined) facts.push(`$${view.totalCostUsd.toFixed(4)}`);
  if (view.failureCode) facts.push(view.failureCode);
  facts.push(durationLabel(view.elapsedMs));
  return facts;
}

function activeElapsedMs(view: RunViewModel, now: number | null) {
  if (now === null) return view.elapsedMs;
  const started = Date.parse(view.startedAt);
  return Number.isFinite(started)
    ? Math.max(view.elapsedMs, now - started)
    : view.elapsedMs;
}

function ribbonSummary(view: RunViewModel) {
  if (
    view.phase !== "queued" &&
    view.phase !== "running" &&
    view.phase !== "waiting_approval"
  ) {
    return view.summary;
  }
  const activeTool = [...view.tools]
    .reverse()
    .find((tool) => tool.status === "running" || tool.status === "waiting");
  return activeTool ? toolActivitySentence(activeTool) : view.summary;
}

function ribbonLabel(view: RunViewModel) {
  if (view.phase !== "completed" || view.tools.length === 0) {
    return phaseLabels[view.phase];
  }
  return toolBatchTitle(view.tools);
}

export function ActivitySummary({
  activity,
  responseStarted = false,
}: {
  activity: RunActivity;
  responseStarted?: boolean;
}) {
  const observed = useRunViewModel();
  const view =
    observed?.runId === activity.run_id
      ? observed
      : reduceRunViewModel(undefined, activity);
  const [manualDisclosure, setManualDisclosure] = useState<{
    runId: string;
    open: boolean;
  } | null>(null);
  const manuallyOpen =
    manualDisclosure?.runId === view.runId ? manualDisclosure.open : null;
  const active =
    view.phase === "queued" ||
    view.phase === "running" ||
    view.phase === "waiting_approval";
  const [now, setNow] = useState<number | null>(null);
  useEffect(() => {
    if (!active) {
      setNow(null);
      return;
    }
    const tick = () => setNow(Date.now());
    tick();
    const timer = window.setInterval(tick, 1_000);
    return () => window.clearInterval(timer);
  }, [active, view.runId]);
  const open = manuallyOpen ?? !responseStarted;
  const facts = ribbonFacts({
    ...view,
    elapsedMs: activeElapsedMs(view, now),
  });
  const timeline = executionTimeline(view);
  const model = [...view.items]
    .reverse()
    .find((item) => item.event_type === "model.route.selected")?.summary;

  function toggleDisclosure(event: MouseEvent<HTMLElement>) {
    event.preventDefault();
    setManualDisclosure({ runId: view.runId, open: !open });
  }

  return (
    <details
      className={`execution-ribbon phase-${view.phase}`}
      aria-label={`执行进度 ${view.runId}`}
      data-run-id={view.runId}
      data-response-started={responseStarted ? "true" : "false"}
      open={open}
    >
      <summary onClick={toggleDisclosure} aria-expanded={open}>
        <span className="execution-state-mark" aria-hidden="true"><i /></span>
        <span className="execution-phase">{ribbonLabel(view)}</span>
        <span className="execution-summary">{ribbonSummary(view)}</span>
        <span className="execution-facts">
          {facts.map((fact) => (
            <span key={fact}>{fact}</span>
          ))}
        </span>
        <span className="execution-chevron" aria-hidden="true" />
      </summary>
      <div className="execution-tree">
        {timeline.length > 0 && (
          <section className="execution-log" aria-label="思考与行动">
            {timeline.map((entry) =>
              entry.kind === "commentary" ? (
                <p className="execution-commentary" key={entry.commentary.id}>
                  {entry.commentary.text}
                </p>
              ) : entry.kind === "task" ? (
                <TaskRow key={entry.task.id} task={entry.task} />
              ) : (
                <ToolRow key={entry.tool.id} tool={entry.tool} />
              ),
            )}
          </section>
        )}
        {model && (
          <section className="execution-runtime" aria-label="运行模型">
            <h4>运行模型</h4>
            <code>{model}</code>
          </section>
        )}
        {timeline.length === 0 && (
          <p className="execution-empty">{view.summary}</p>
        )}
      </div>
    </details>
  );
}
