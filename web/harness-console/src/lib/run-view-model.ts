import type { ActivityItem, RunActivity } from "./activity-schema";

export type RunPhase =
  | "queued"
  | "running"
  | "waiting_approval"
  | "completed"
  | "failed"
  | "rejected"
  | "cancelled";

export type WorkStatus = "running" | "waiting" | "completed" | "failed";

export interface RunTaskNode {
  id: string;
  parentId?: string;
  title: string;
  status: WorkStatus;
  sequence: number;
  alias?: string;
  agentVersion?: string;
  durationMs?: number;
  toolUses?: number;
}

export interface RunToolNode {
  id: string;
  name: string;
  status: WorkStatus;
  sequence: number;
  arguments?: Record<string, unknown>;
  resultSummary?: string;
}

export interface RunViewModel {
  runId: string;
  phase: RunPhase;
  startedAt: string;
  updatedAt: string;
  elapsedMs: number;
  summary: string;
  items: ActivityItem[];
  tasks: RunTaskNode[];
  tools: RunToolNode[];
  taskCount: number;
  toolCount: number;
  pendingApprovalId?: string;
}

const terminalPhases = new Set<RunPhase>([
  "completed",
  "failed",
  "rejected",
  "cancelled",
]);

function mergedItems(
  previous: RunViewModel | undefined,
  activity: RunActivity,
): ActivityItem[] {
  const byId = new Map<string, ActivityItem>();
  if (previous?.runId === activity.run_id) {
    for (const item of previous.items) byId.set(item.id, item);
  }
  for (const item of activity.items) byId.set(item.id, item);
  return [...byId.values()].sort((left, right) => left.sequence - right.sequence);
}

function terminalPhase(items: readonly ActivityItem[]): RunPhase | undefined {
  for (const item of [...items].reverse()) {
    if (item.event_type === "run.succeeded") return "completed";
    if (item.event_type === "run.cancelled") return "cancelled";
    if (item.event_type === "run.rejected") return "rejected";
    if (item.event_type === "run.failed" || item.event_type === "run.timed_out") {
      return "failed";
    }
  }
  return undefined;
}

function pendingApproval(items: readonly ActivityItem[]): string | undefined {
  const pending = new Map<string, string>();
  for (const item of items) {
    const approvalId = item.metadata.approval_id;
    if (typeof approvalId !== "string") continue;
    if (item.event_type === "approval.requested") {
      pending.set(approvalId, approvalId);
    } else if (
      item.event_type === "approval.approved" ||
      item.event_type === "approval.rejected"
    ) {
      pending.delete(approvalId);
    }
  }
  return [...pending.keys()].at(-1);
}

function phaseFor(
  previous: RunViewModel | undefined,
  items: readonly ActivityItem[],
): RunPhase {
  if (previous && terminalPhases.has(previous.phase)) return previous.phase;
  const terminal = terminalPhase(items);
  if (terminal) return terminal;
  if (pendingApproval(items)) return "waiting_approval";
  const latestRun = [...items].reverse().find((item) => item.event_type.startsWith("run."));
  return latestRun?.event_type === "run.queued" ? "queued" : "running";
}

function workStatus(item: ActivityItem): WorkStatus {
  if (item.status === "failed") return "failed";
  if (item.status === "waiting") return "waiting";
  if (item.status === "succeeded" || item.status === "completed") return "completed";
  return "running";
}

function taskNodes(items: readonly ActivityItem[]): RunTaskNode[] {
  const tasks = new Map<string, RunTaskNode>();
  const delegatedToolCalls = new Set(
    items.flatMap((item) => {
      const taskId = item.metadata.task_id;
      const parentId = item.metadata.parent_tool_use_id;
      return item.kind === "subagent" &&
        typeof taskId === "string" &&
        typeof parentId === "string"
        ? [parentId]
        : [];
    }),
  );
  for (const item of items) {
    if (item.kind !== "subagent") continue;
    const realTaskId = item.metadata.task_id;
    const toolCallId = item.metadata.tool_call_id;
    if (
      typeof realTaskId !== "string" &&
      typeof toolCallId === "string" &&
      delegatedToolCalls.has(toolCallId)
    ) {
      continue;
    }
    const taskId = realTaskId ?? toolCallId ?? item.id;
    if (typeof taskId !== "string") continue;
    const parent = item.metadata.parent_tool_use_id;
    const existing = tasks.get(taskId);
    tasks.set(taskId, {
      id: taskId,
      parentId: typeof parent === "string" ? parent : undefined,
      title: item.summary || item.title,
      status: workStatus(item),
      sequence: existing?.sequence ?? item.sequence,
      alias: typeof item.metadata.alias === "string" ? item.metadata.alias : undefined,
      agentVersion:
        typeof item.metadata.agent_version === "string"
          ? item.metadata.agent_version
          : undefined,
      durationMs:
        typeof item.metadata.duration_ms === "number"
          ? item.metadata.duration_ms
          : undefined,
      toolUses:
        typeof item.metadata.usage === "object" &&
        item.metadata.usage !== null &&
        typeof (item.metadata.usage as { tool_uses?: unknown }).tool_uses === "number"
          ? (item.metadata.usage as { tool_uses: number }).tool_uses
          : undefined,
    });
  }
  return [...tasks.values()].sort((left, right) => left.sequence - right.sequence);
}

function toolNodes(items: readonly ActivityItem[]): RunToolNode[] {
  const tools = new Map<string, RunToolNode>();
  for (const item of items) {
    const rawToolCallId = item.metadata.tool_call_id;
    const toolCallId =
      typeof rawToolCallId === "string"
        ? rawToolCallId
        : item.event_type === "tool.request"
          ? item.id
          : undefined;
    if (!toolCallId) continue;
    if (item.event_type === "tool.request" && item.kind === "tool") {
      const argumentsValue = item.metadata.arguments;
      tools.set(toolCallId, {
        id: toolCallId,
        name: typeof item.metadata.name === "string" ? item.metadata.name : "工具",
        status: "running",
        sequence: item.sequence,
        arguments:
          typeof argumentsValue === "object" &&
          argumentsValue !== null &&
          !Array.isArray(argumentsValue)
            ? argumentsValue as Record<string, unknown>
            : undefined,
      });
      continue;
    }
    if (item.event_type === "approval.requested") {
      const tool = tools.get(toolCallId);
      if (tool) tools.set(toolCallId, { ...tool, status: "waiting" });
      continue;
    }
    if (item.event_type === "tool.result") {
      const tool = tools.get(toolCallId);
      if (tool) {
        tools.set(toolCallId, {
          ...tool,
          status: item.status === "failed" ? "failed" : "completed",
          resultSummary:
            typeof item.metadata.result_summary === "string"
              ? item.metadata.result_summary
              : undefined,
        });
      }
    }
  }
  return [...tools.values()].sort((left, right) => left.sequence - right.sequence);
}

export function reduceRunViewModel(
  previous: RunViewModel | undefined,
  activity: RunActivity,
): RunViewModel {
  const items = mergedItems(previous, activity);
  const tasks = taskNodes(items);
  const tools = toolNodes(items);
  const lastTimestamp = items.at(-1)?.timestamp ?? activity.started_at;
  const started = Date.parse(activity.started_at);
  const updated = Date.parse(lastTimestamp);
  const latestActive = [...items]
    .reverse()
    .find(
      (item) =>
        ![
          "run.queued",
          "run.provisioning",
          // Routing is an auditable per-Run fact, not a user-visible unit of
          // work. Keep it in Run details without replacing the active status.
          "model.route.selected",
        ].includes(item.event_type),
    );
  return {
    runId: activity.run_id,
    phase: phaseFor(previous?.runId === activity.run_id ? previous : undefined, items),
    startedAt: activity.started_at,
    updatedAt: lastTimestamp,
    elapsedMs:
      Number.isFinite(started) && Number.isFinite(updated)
        ? Math.max(0, updated - started)
        : 0,
    summary: latestActive?.title ?? "准备执行",
    items,
    tasks,
    tools,
    taskCount: tasks.length,
    toolCount: tools.length,
    pendingApprovalId: pendingApproval(items),
  };
}

export function selectComposerDisabled(
  model: Pick<RunViewModel, "phase"> | undefined,
): boolean {
  return model?.phase === "queued" ||
    model?.phase === "running" ||
    model?.phase === "waiting_approval";
}
