import { z } from "zod";

export const activityItemSchema = z.object({
  id: z.string(),
  event_type: z.string(),
  kind: z.enum(["run", "analysis", "tool", "subagent", "artifact", "result", "error"]),
  status: z.string(),
  title: z.string(),
  summary: z.string().nullish(),
  timestamp: z.string(),
  sequence: z.number(),
  metadata: z.record(z.string(), z.unknown()).default({}),
});

export const runActivitySchema = z.object({
  run_id: z.string(),
  status: z.string(),
  started_at: z.string(),
  items: z.array(activityItemSchema),
  metrics: z.record(z.string(), z.unknown()).default({}),
});

export type ActivityItem = z.infer<typeof activityItemSchema>;
export type RunActivity = z.infer<typeof runActivitySchema>;

export function latestRunActivity(messages: readonly unknown[]): RunActivity | undefined {
  for (let index = messages.length - 1; index >= 0; index -= 1) {
    const message = messages[index] as Record<string, unknown> | undefined;
    if (message?.role !== "activity" || message.activityType !== "harness.run.v1") continue;
    const parsed = runActivitySchema.safeParse(message.content);
    if (parsed.success) return parsed.data;
  }
  return undefined;
}

export interface ActivityOverview {
  model: string;
  provider: string;
  duration: string;
  turns: string;
  cost: string;
  stopReason: string;
  toolCalls: number;
  subagents: number;
}

export function activityOverview(activity: RunActivity): ActivityOverview {
  const route = [...activity.items]
    .reverse()
    .find((item) => item.event_type === "model.route.selected");
  const first = Date.parse(activity.started_at);
  const last = Date.parse(activity.items.at(-1)?.timestamp ?? activity.started_at);
  const durationMs = Number.isFinite(first) && Number.isFinite(last) ? Math.max(0, last - first) : 0;
  const cost = activity.metrics.cost_usd;
  const taskIds = new Set(
    activity.items
      .filter((item) => item.kind === "subagent")
      .map((item) => item.metadata.task_id)
      .filter((id): id is string => typeof id === "string"),
  );

  return {
    model: String(route?.metadata.model ?? route?.summary ?? "—"),
    provider: String(route?.metadata.provider ?? "—"),
    duration: durationMs < 1000 ? `${durationMs}ms` : `${(durationMs / 1000).toFixed(1)}s`,
    turns: activity.metrics.turns == null ? "—" : String(activity.metrics.turns),
    cost: typeof cost === "number" ? `$${cost.toFixed(4)}` : "—",
    stopReason: activity.metrics.stop_reason == null ? "—" : String(activity.metrics.stop_reason),
    toolCalls: activity.items.filter((item) => item.event_type === "tool.request").length,
    subagents: taskIds.size || activity.items.filter((item) => item.kind === "subagent").length,
  };
}
