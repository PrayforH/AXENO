"use client";

import { TextMessagePartProvider } from "@assistant-ui/react";
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
import { toolActivitySentence } from "../lib/tool-presentation";
import { MarkdownText } from "./markdown-text";

const phaseLabels: Record<RunPhase, string> = {
  queued: "等待处理",
  running: "正在处理",
  waiting_approval: "等待审批",
  completed: "处理完成",
  failed: "处理失败",
  rejected: "已拒绝",
  cancelled: "已停止",
};

const disclosureMemory = new Map<string, boolean>();
const DISCLOSURE_STORAGE_PREFIX = "agent-studio:run-disclosure:v1:";

function storedDisclosure(runId: string): boolean | null {
  const remembered = disclosureMemory.get(runId);
  if (remembered !== undefined) return remembered;
  if (typeof window === "undefined") return null;
  try {
    const stored = window.localStorage.getItem(
      `${DISCLOSURE_STORAGE_PREFIX}${runId}`,
    );
    if (stored !== "open" && stored !== "closed") return null;
    const open = stored === "open";
    disclosureMemory.set(runId, open);
    return open;
  } catch {
    return null;
  }
}

function rememberDisclosure(runId: string, open: boolean) {
  disclosureMemory.set(runId, open);
  try {
    window.localStorage.setItem(
      `${DISCLOSURE_STORAGE_PREFIX}${runId}`,
      open ? "open" : "closed",
    );
  } catch {
    // Browser storage may be unavailable in hardened/private contexts. The
    // module cache still preserves the choice while this page remains open.
  }
}

function durationLabel(elapsedMs: number) {
  if (elapsedMs < 1_000) return `${elapsedMs}ms`;
  if (elapsedMs < 60_000) return `${Math.round(elapsedMs / 1_000)}s`;
  const minutes = Math.floor(elapsedMs / 60_000);
  const seconds = Math.round((elapsedMs % 60_000) / 1_000);
  return `${minutes}m ${seconds}s`;
}

interface CommentaryNode {
  id: string;
  text: string;
  sequence: number;
}

type ProcessCategory = "setup" | "model" | "result";

interface ProcessNode {
  id: string;
  eventType: string;
  title: string;
  summary?: string;
  status: WorkStatus;
  category: ProcessCategory;
  sequence: number;
}

type RawTimelineNode =
  | { kind: "commentary"; sequence: number; commentary: CommentaryNode }
  | { kind: "process"; sequence: number; process: ProcessNode }
  | { kind: "task"; sequence: number; task: RunTaskNode }
  | { kind: "tool"; sequence: number; tool: RunToolNode };

type ActionIconKind = "system" | "model" | "terminal" | "edit" | "search" | "agent" | "result";

interface ActionNode {
  id: string;
  label: string;
  detail?: string;
  entries?: ActionEntry[];
  resultPreview?: string;
  icon: ActionIconKind;
  status: WorkStatus;
  sequence: number;
}

interface ActionEntry {
  id: string;
  label: string;
  result: string;
  preview?: string;
  status: WorkStatus;
}

type DisplayTimelineNode =
  | { kind: "commentary"; sequence: number; commentary: CommentaryNode }
  | { kind: "action"; sequence: number; action: ActionNode };

const visibleProcessEvents = new Set([
  "run.provisioning",
  "workspace.restored",
  "agent.assets.staged",
  "run.running",
  "policy.resolved",
  "credential.lease.issued",
  "tool.directory.loaded",
  "tool.directory.degraded",
  "runtime.result",
  "workspace.archived",
  "workspace.recovery_retained",
  "artifact.ready",
]);

function processCategory(eventType: string): ProcessCategory {
  if (["runtime.system", "message.start"].includes(eventType)) return "model";
  if (["runtime.result", "workspace.archived", "artifact.ready"].includes(eventType)) {
    return "result";
  }
  return "setup";
}

function processNodes(view: RunViewModel): ProcessNode[] {
  const latestSequence = view.items.at(-1)?.sequence ?? 0;
  return view.items.flatMap((item) => {
    if (!visibleProcessEvents.has(item.event_type)) return [];
    const rawStatus =
      item.status === "failed"
        ? "failed"
        : item.status === "waiting"
          ? "waiting"
          : item.status === "succeeded" || item.status === "completed"
            ? "completed"
            : "running";
    return [{
      id: item.id,
      eventType: item.event_type,
      title: item.title,
      summary: item.summary?.trim() || undefined,
      status:
        rawStatus === "running" && item.sequence < latestSequence
          ? "completed"
          : rawStatus,
      category: processCategory(item.event_type),
      sequence: item.sequence,
    } satisfies ProcessNode];
  });
}

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
    // A trailing message is still ambiguous while the Run is active: the
    // live response owns it so Markdown can stream without duplication. Only
    // text proven to precede an auditable action belongs in the process log.
    if (nextAction === undefined) continue;
    const groupKey = nextAction;
    const existing = grouped.get(groupKey);
    grouped.set(groupKey, {
      id: existing?.id ?? item.id,
      sequence: existing?.sequence ?? item.sequence,
      text: `${existing?.text ?? ""}${item.summary}`,
    });
  }
  return [...grouped.values()];
}

function ExecutionCommentary({ text }: { text: string }) {
  return (
    <div className="execution-commentary">
      <TextMessagePartProvider text={text} isRunning={false}>
        <MarkdownText />
      </TextMessagePartProvider>
    </div>
  );
}

function rawTimeline(view: RunViewModel): RawTimelineNode[] {
  return [
    ...processNodes(view).map(
      (process): RawTimelineNode => ({
        kind: "process",
        sequence: process.sequence,
        process,
      }),
    ),
    ...commentaryNodes(view).map(
      (commentary): RawTimelineNode => ({
        kind: "commentary",
        sequence: commentary.sequence,
        commentary,
      }),
    ),
    ...view.tasks.map(
      (task): RawTimelineNode => ({ kind: "task", sequence: task.sequence, task }),
    ),
    ...view.tools.map(
      (tool): RawTimelineNode => ({ kind: "tool", sequence: tool.sequence, tool }),
    ),
  ].sort((left, right) => left.sequence - right.sequence);
}

function combinedStatus(statuses: readonly WorkStatus[]): WorkStatus {
  if (statuses.includes("failed")) return "failed";
  if (statuses.includes("waiting")) return "waiting";
  if (statuses.includes("running")) return "running";
  return "completed";
}

function processAction(processes: readonly ProcessNode[]): ActionNode {
  const category = processes[0]?.category ?? "setup";
  const status = combinedStatus(processes.map((item) => item.status));
  const active = status === "running" || status === "waiting";
  const detailParts = processes
    .flatMap((item) => [item.title, item.summary])
    .filter((value, index, values): value is string => Boolean(value) && values.indexOf(value) === index);
  const label =
    category === "setup"
      ? active ? "正在准备运行环境" : "已准备运行环境"
      : category === "model"
        ? active ? "模型正在处理" : "模型处理完成"
        : active ? "正在整理本轮结果" : "已完成本轮处理";
  return {
    id: processes.map((item) => item.id).join("-"),
    label,
    detail: detailParts.join(" · "),
    icon: category === "setup" ? "system" : category === "model" ? "model" : "result",
    status,
    sequence: processes[0]?.sequence ?? 0,
  };
}

function toolGroupLabel(tools: readonly RunToolNode[]) {
  if (tools.length === 1) return toolActivitySentence(tools[0]);
  const counts = new Map<string, number>();
  for (const tool of tools) counts.set(tool.name, (counts.get(tool.name) ?? 0) + 1);
  const labels: string[] = [];
  const glob = counts.get("Glob") ?? 0;
  const grep = counts.get("Grep") ?? 0;
  const read = counts.get("Read") ?? 0;
  const bash = counts.get("Bash") ?? 0;
  const edits = (counts.get("Write") ?? 0) + (counts.get("Edit") ?? 0);
  const web = [...counts.entries()]
    .filter(([name]) => ["WebSearch", "WebFetch"].includes(name) || name.includes("tavily"))
    .reduce((total, [, count]) => total + count, 0);
  if (glob) labels.push(`查找了 ${glob} 次文件`);
  if (grep) labels.push(`搜索了 ${grep} 次内容`);
  if (read) labels.push(`读取了 ${read} 个文件`);
  if (bash) labels.push(`运行了 ${bash} 个命令`);
  if (edits) labels.push(`编辑了 ${edits} 个文件`);
  if (web) labels.push(`访问了 ${web} 个网页`);
  const described = glob + grep + read + bash + edits + web;
  if (described < tools.length) labels.push(`调用了 ${tools.length - described} 个工具`);
  return labels.join(" · ");
}

function toolIcon(tools: readonly RunToolNode[]): ActionIconKind {
  if (tools.every((tool) => tool.name === "Bash")) return "terminal";
  if (tools.every((tool) => ["Write", "Edit"].includes(tool.name))) return "edit";
  return "search";
}

function completeArgumentText(value: unknown): string | undefined {
  if (typeof value === "string") return value.replace(/\s+/g, " ").trim() || undefined;
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  if (Array.isArray(value)) {
    const items = value
      .map(completeArgumentText)
      .filter((item): item is string => Boolean(item));
    return items.length > 0 ? items.join("、") : undefined;
  }
  return undefined;
}

function completeToolSentence(tool: RunToolNode) {
  const argument = (...keys: string[]) => {
    for (const key of keys) {
      const value = completeArgumentText(tool.arguments?.[key]);
      if (value) return value;
    }
    return undefined;
  };
  const path = argument("file_path", "path");
  const pattern = argument("pattern", "glob");
  const active = tool.status === "running" || tool.status === "waiting";
  const verb = (running: string, completed: string) => active ? running : completed;

  switch (tool.name) {
    case "Glob":
      return `${verb("正在查找", "已查找")}文件${pattern ? ` ${pattern}` : ""}${path ? `，范围 ${path}` : ""}`;
    case "Grep":
      return pattern
        ? `${verb("正在", "已在")} ${path ?? "工作区"} 中搜索“${pattern}”`
        : `${verb("正在搜索", "已搜索")}内容${path ? `，范围 ${path}` : ""}`;
    case "Read":
      return `${verb("正在读取", "已读取")}${path ? ` ${path}` : "文件"}`;
    case "Write":
      return `${verb("正在创建", "已创建")}${path ? ` ${path}` : "文件"}`;
    case "Edit":
      return `${verb("正在编辑", "已编辑")}${path ? ` ${path}` : "文件"}`;
    case "Bash": {
      const command = argument("command", "description");
      return `${verb("正在运行", "已运行")}${command ? ` ${command}` : "命令"}`;
    }
    case "WebSearch": {
      const query = argument("query");
      return `${verb("正在搜索", "已搜索")}${query ? `“${query}”` : "网页"}`;
    }
    case "WebFetch": {
      const url = argument("url");
      return `${verb("正在读取", "已读取")}${url ? ` ${url}` : "网页"}`;
    }
    default:
      return toolActivitySentence(tool);
  }
}

function toolResultLabel(tool: RunToolNode) {
  if (tool.resultSummary) return tool.resultSummary;
  if (tool.status === "failed") return "失败";
  if (tool.status === "waiting") return "等待审批";
  if (tool.status === "running") return "运行中";
  return "已完成";
}

function toolAction(tools: readonly RunToolNode[]): ActionNode {
  return {
    id: tools.map((tool) => tool.id).join("-"),
    label: toolGroupLabel(tools),
    detail: tools.length === 1 ? tools[0].resultSummary : undefined,
    resultPreview: tools.length === 1 ? tools[0].resultPreview : undefined,
    entries: tools.length > 1
      ? tools.map((tool) => ({
          id: tool.id,
          label: completeToolSentence(tool),
          result: toolResultLabel(tool),
          preview: tool.resultPreview,
          status: tool.status,
        }))
      : undefined,
    icon: toolIcon(tools),
    status: combinedStatus(tools.map((tool) => tool.status)),
    sequence: tools[0]?.sequence ?? 0,
  };
}

function taskAction(tasks: readonly RunTaskNode[]): ActionNode {
  const aliases = tasks
    .map((task) => task.alias ?? task.title)
    .filter((value, index, values) => values.indexOf(value) === index);
  return {
    id: tasks.map((task) => task.id).join("-"),
    label:
      tasks.length === 1
        ? `${tasks[0].status === "running" ? "正在运行" : "运行了"}子任务 ${aliases[0]}`
        : `运行了 ${tasks.length} 个子任务`,
    detail: tasks.length > 1 ? aliases.join(" · ") : undefined,
    icon: "agent",
    status: combinedStatus(tasks.map((task) => task.status)),
    sequence: tasks[0]?.sequence ?? 0,
  };
}

function activityHeading(view: RunViewModel) {
  if (view.phase !== "completed") return phaseLabels[view.phase];
  if (view.tools.length > 0) return toolGroupLabel(view.tools);
  if (view.tasks.length === 1) {
    return `完成子任务 ${view.tasks[0].alias ?? view.tasks[0].title}`;
  }
  if (view.tasks.length > 1) return `完成 ${view.tasks.length} 个子任务`;
  return phaseLabels.completed;
}

function failureDetails(view: RunViewModel) {
  const failure = [...view.items]
    .reverse()
    .find(
      (item) =>
        item.event_type === "run.failed" ||
        item.event_type === "run.timed_out" ||
        item.event_type === "run.rejected",
    );
  const failedActions = view.tools.filter((tool) => tool.status === "failed").length +
    view.tasks.filter((task) => task.status === "failed").length;
  return {
    title: failure?.title || "本次处理未完成",
    summary:
      failure?.summary?.trim() ||
      "请检查下方最后一个失败动作及其返回结果后重试。",
    failedActions,
  };
}

function displayTimeline(view: RunViewModel): DisplayTimelineNode[] {
  const raw = rawTimeline(view);
  const display: DisplayTimelineNode[] = [];
  for (let index = 0; index < raw.length;) {
    const current = raw[index];
    if (current.kind === "commentary") {
      display.push(current);
      index += 1;
      continue;
    }
    if (current.kind === "process") {
      const group = [current.process];
      let cursor = index + 1;
      while (cursor < raw.length) {
        const candidate = raw[cursor];
        if (
          candidate.kind !== "process" ||
          candidate.process.category !== current.process.category
        ) break;
        group.push(candidate.process);
        cursor += 1;
      }
      const action = processAction(group);
      display.push({ kind: "action", sequence: action.sequence, action });
      index = cursor;
      continue;
    }
    if (current.kind === "tool") {
      const group = [current.tool];
      let cursor = index + 1;
      while (cursor < raw.length) {
        const candidate = raw[cursor];
        if (candidate.kind !== "tool") break;
        group.push(candidate.tool);
        cursor += 1;
      }
      const action = toolAction(group);
      display.push({ kind: "action", sequence: action.sequence, action });
      index = cursor;
      continue;
    }
    const group = [current.task];
    let cursor = index + 1;
    while (cursor < raw.length) {
      const candidate = raw[cursor];
      if (candidate.kind !== "task") break;
      group.push(candidate.task);
      cursor += 1;
    }
    const action = taskAction(group);
    display.push({ kind: "action", sequence: action.sequence, action });
    index = cursor;
  }
  return display;
}

function ActionIcon({ kind }: { kind: ActionIconKind }) {
  if (kind === "terminal") {
    return <svg viewBox="0 0 20 20" aria-hidden="true"><rect x="2.5" y="3" width="15" height="14" rx="3" /><path d="m6 8 2 2-2 2m4.5 0h3" /></svg>;
  }
  if (kind === "edit") {
    return <svg viewBox="0 0 20 20" aria-hidden="true"><path d="m4 14.8.8-3.8L13 2.8a2 2 0 0 1 2.8 2.8l-8.2 8.2-3.6 1Z" /><path d="m11.8 4 3 3" /></svg>;
  }
  if (kind === "search") {
    return <svg viewBox="0 0 20 20" aria-hidden="true"><path d="M11.8 3.2a4.2 4.2 0 0 0-5.1 5.1L2.9 12l-1 3 3-1 3.8-3.8a4.2 4.2 0 0 0 5.1-5.1l-2.4 2.4-2-2 2.4-2.3Z" /></svg>;
  }
  if (kind === "agent") {
    return <svg viewBox="0 0 20 20" aria-hidden="true"><circle cx="10" cy="6" r="3" /><path d="M4 17c.5-3.5 2.5-5.3 6-5.3s5.5 1.8 6 5.3" /></svg>;
  }
  if (kind === "result") {
    return <svg viewBox="0 0 20 20" aria-hidden="true"><path d="M4 3.5h9l3 3V17H4Z" /><path d="M13 3.5V7h3M7 11l2 2 4-4" /></svg>;
  }
  if (kind === "model") {
    return <svg viewBox="0 0 20 20" aria-hidden="true"><path d="M10 2.5v3M10 14.5v3M2.5 10h3M14.5 10h3M4.7 4.7l2.1 2.1M13.2 13.2l2.1 2.1M15.3 4.7l-2.1 2.1M6.8 13.2l-2.1 2.1" /><circle cx="10" cy="10" r="3.2" /></svg>;
  }
  return <svg viewBox="0 0 20 20" aria-hidden="true"><path d="M3 6.5h14M5 3v3.5M15 3v3.5M4 6.5V17h12V6.5M7 10h6M7 13h4" /></svg>;
}

export function formatResultPreview(value: string) {
  const trimmed = value.trim();
  if (!trimmed || (!trimmed.startsWith("{") && !trimmed.startsWith("["))) {
    return value;
  }
  try {
    return JSON.stringify(JSON.parse(trimmed), null, 2);
  } catch {
    return value;
  }
}

function ResultPreview({
  children,
  label,
}: {
  children: string;
  label: string;
}) {
  return (
    <pre
      className="execution-action-result"
      role="region"
      aria-label={label}
      tabIndex={0}
    >
      <code>{formatResultPreview(children)}</code>
    </pre>
  );
}

function ActionRow({ action }: { action: ActionNode }) {
  const hasResult = Boolean(action.resultPreview || action.entries?.length);
  const heading = (
    <>
      <span className="execution-action-icon"><ActionIcon kind={action.icon} /></span>
      <span className="execution-action-copy">
        <span className="execution-action-heading">
          <strong>{action.label}</strong>
          {action.detail && <small>{action.detail}</small>}
        </span>
      </span>
    </>
  );
  const result = (
    <div className="execution-action-body">
      {action.resultPreview && (
        <ResultPreview label="处理结果预览">
          {action.resultPreview}
        </ResultPreview>
      )}
      {action.entries && (
        <div className="execution-action-details">
          {action.entries.map((entry) => (
            <div
              className={`execution-action-detail action-${entry.status}`}
              key={entry.id}
            >
              <div className="execution-action-detail-heading">
                <span>{entry.label}</span>
                <small>{entry.result}</small>
              </div>
              {entry.preview && (
                <ResultPreview label={`${entry.label} 结果预览`}>
                  {entry.preview}
                </ResultPreview>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );

  if (!hasResult) {
    return (
      <div className={`execution-action action-${action.status}`}>
        <span className="execution-action-static">{heading}</span>
      </div>
    );
  }

  return (
    <details className={`execution-action action-${action.status}`}>
      <summary className="execution-action-summary">
        {heading}
        <span className="execution-action-chevron" aria-hidden="true" />
      </summary>
      {result}
    </details>
  );
}

function activeElapsedMs(view: RunViewModel, now: number | null) {
  if (now === null) return view.elapsedMs;
  const started = Date.parse(view.startedAt);
  return Number.isFinite(started)
    ? Math.max(view.elapsedMs, now - started)
    : view.elapsedMs;
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
  } | null>(() => {
    const remembered = storedDisclosure(view.runId);
    return remembered === null
      ? null
      : { runId: view.runId, open: remembered };
  });
  useEffect(() => {
    const remembered = storedDisclosure(view.runId);
    setManualDisclosure(
      remembered === null
        ? null
        : { runId: view.runId, open: remembered },
    );
  }, [view.runId]);
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
  // Successful work folds into the answer. Failed work stays open so the
  // action trail and the final diagnostic are visible without another click.
  const open = manuallyOpen ?? (active || view.phase === "failed");
  const elapsed = activeElapsedMs(view, now);
  const timeline = displayTimeline(view);
  const heading = activityHeading(view);
  const failure = view.phase === "failed" ? failureDetails(view) : null;

  function toggleDisclosure(_event: MouseEvent<HTMLButtonElement>) {
    const nextOpen = !open;
    rememberDisclosure(view.runId, nextOpen);
    setManualDisclosure({ runId: view.runId, open: nextOpen });
  }

  return (
    <section
      className={`execution-ribbon phase-${view.phase}`}
      aria-label={`执行进度 ${view.runId}`}
      data-run-id={view.runId}
      data-response-started={responseStarted ? "true" : "false"}
      data-open={open ? "true" : "false"}
    >
      <button
        type="button"
        className="execution-disclosure"
        onClick={toggleDisclosure}
        aria-expanded={open}
      >
        <span className="execution-phase">{heading}</span>
        <span className="execution-duration">{durationLabel(elapsed)}</span>
        <span className="execution-chevron" aria-hidden="true" />
      </button>
      <div className="execution-tree" hidden={!open}>
        {failure ? (
          <section className="execution-failure-diagnostic" aria-label="失败定位">
            <span>失败定位</span>
            <strong>{failure.title}</strong>
            <p>{failure.summary}</p>
            <small>
              {[
                view.turns !== undefined ? `${view.turns} 个模型回合` : null,
                view.toolCount > 0 ? `${view.toolCount} 个工具动作` : null,
                view.taskCount > 0 ? `${view.taskCount} 个子任务` : null,
                failure.failedActions > 0
                  ? `${failure.failedActions} 个动作失败`
                  : null,
              ].filter(Boolean).join(" · ")}
            </small>
          </section>
        ) : null}
        {timeline.length > 0 ? (
          <section className="execution-log" aria-label="处理过程">
            {timeline.map((entry) =>
              entry.kind === "commentary" ? (
                <ExecutionCommentary
                  key={entry.commentary.id}
                  text={entry.commentary.text}
                />
              ) : (
                <ActionRow key={entry.action.id} action={entry.action} />
              ),
            )}
          </section>
        ) : (
          <p className="execution-empty">{view.summary}</p>
        )}
      </div>
    </section>
  );
}
