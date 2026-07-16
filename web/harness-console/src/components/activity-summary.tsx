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

const standaloneToolNames = new Set([
  "Task",
  "Agent",
  "harness_request_approval",
  "harness_present_artifact",
  "harness_run_activity",
]);

function isFoldableTool(tool: RunToolNode) {
  return tool.status === "completed" && !standaloneToolNames.has(tool.name);
}

type ToolDisplayNode =
  | { kind: "tool"; tool: RunToolNode }
  | { kind: "processed"; tools: RunToolNode[] };

export function groupProcessedTools(tools: readonly RunToolNode[]): ToolDisplayNode[] {
  const processed = tools.filter(isFoldableTool);
  if (processed.length < 2) {
    return tools.map((tool) => ({ kind: "tool", tool }));
  }
  const processedIds = new Set(processed.map((tool) => tool.id));
  const firstId = processed[0].id;
  return tools.flatMap((tool): ToolDisplayNode[] => {
    if (!processedIds.has(tool.id)) return [{ kind: "tool", tool }];
    return tool.id === firstId ? [{ kind: "processed", tools: processed }] : [];
  });
}

function processedDigest(tools: readonly RunToolNode[]) {
  const counts = new Map<string, number>();
  for (const tool of tools) counts.set(tool.name, (counts.get(tool.name) ?? 0) + 1);
  return [...counts]
    .map(([name, count]) => count > 1 ? `${name} ×${count}` : name)
    .join(" · ");
}

function ProcessedTools({ tools }: { tools: RunToolNode[] }) {
  return (
    <details className="execution-tool-batch">
      <summary>
        <span className="execution-batch-chevron" aria-hidden="true" />
        <span>已处理 {tools.length} 项</span>
        <small>{processedDigest(tools)}</small>
      </summary>
      <div className="execution-tool-batch-items">
        {tools.map((tool) => <ToolRow key={tool.id} tool={tool} />)}
      </div>
    </details>
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
  const displayedTools = groupProcessedTools(view.tools);

  return (
    <details
      className={`execution-ribbon phase-${view.phase}`}
      aria-label="执行进度"
    >
      <summary>
        <span className="execution-state-mark" aria-hidden="true"><i /></span>
        <span className="execution-phase">{phaseLabels[view.phase]}</span>
        <span className="execution-summary">{view.summary}</span>
        <span className="execution-facts">
          {facts.map((fact) => (
            <span key={fact}>{fact}</span>
          ))}
        </span>
        <span className="execution-chevron" aria-hidden="true" />
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
            {displayedTools.map((node) => node.kind === "processed" ? (
              <ProcessedTools key={`processed-${node.tools[0].id}`} tools={node.tools} />
            ) : (
              <ToolRow key={node.tool.id} tool={node.tool} />
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
