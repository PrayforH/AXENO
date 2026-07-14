"use client";

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

const phaseLabels: Record<RunPhase, string> = {
  queued: "等待执行",
  running: "正在执行",
  waiting_approval: "等待审批",
  completed: "执行完成",
  failed: "执行失败",
  rejected: "执行被拒绝",
  cancelled: "执行已停止",
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
        <span>{task.title}</span>
        <small>{workLabels[task.status]}</small>
      </summary>
      <div className="execution-task-detail">
        <code>{task.id}</code>
        {task.parentId && <span>父任务 {task.parentId}</span>}
      </div>
    </details>
  );
}

function ToolRow({ tool }: { tool: RunToolNode }) {
  return (
    <div className={`execution-tool tool-${tool.status}`}>
      <span className="execution-node" aria-hidden="true" />
      <code>{tool.name}</code>
      <small>{workLabels[tool.status]}</small>
    </div>
  );
}

function ribbonFacts(view: RunViewModel) {
  const facts: string[] = [];
  if (view.toolCount > 0) facts.push(`${view.toolCount} 个工具`);
  if (view.taskCount > 0) facts.push(`${view.taskCount} 个子任务`);
  facts.push(durationLabel(view.elapsedMs));
  return facts;
}

export function ActivitySummary({ activity }: { activity: RunActivity }) {
  const observed = useRunViewModel();
  const view =
    observed?.runId === activity.run_id
      ? observed
      : reduceRunViewModel(undefined, activity);
  const facts = ribbonFacts(view);
  const model = [...view.items]
    .reverse()
    .find((item) => item.event_type === "model.route.selected")?.summary;

  return (
    <details
      className={`execution-ribbon phase-${view.phase}`}
      aria-label="执行进度"
    >
      <summary>
        <span className="execution-chevron" aria-hidden="true" />
        <span className="execution-phase">{phaseLabels[view.phase]}</span>
        <span className="execution-summary">{view.summary}</span>
        <span className="execution-facts">
          {facts.map((fact) => (
            <span key={fact}>{fact}</span>
          ))}
        </span>
      </summary>
      <div className="execution-tree">
        {view.tasks.length > 0 && (
          <section aria-label="子任务">
            <h4>子任务</h4>
            {view.tasks.map((task) => (
              <TaskRow key={task.id} task={task} />
            ))}
          </section>
        )}
        {view.tools.length > 0 && (
          <section aria-label="使用的工具">
            <h4>使用的工具</h4>
            {view.tools.map((tool) => (
              <ToolRow key={tool.id} tool={tool} />
            ))}
          </section>
        )}
        {model && (
          <section className="execution-runtime" aria-label="运行模型">
            <h4>运行模型</h4>
            <code>{model}</code>
          </section>
        )}
        {view.tasks.length === 0 && view.tools.length === 0 && (
          <p className="execution-empty">{view.summary}</p>
        )}
      </div>
    </details>
  );
}
