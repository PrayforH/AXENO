import { StructuredValue } from "./structured-value";
import { useRunViewModel } from "../lib/activity-store";
import type { RunToolNode, RunViewModel } from "../lib/run-view-model";

type ToolStatus = "inProgress" | "executing" | "complete";

const statusLabel: Record<ToolStatus, string> = {
  inProgress: "准备中",
  executing: "执行中",
  complete: "已完成",
};

const toolTitles: Record<string, string> = {
  Glob: "查找文件",
  Grep: "搜索内容",
  Read: "读取文件",
  Write: "创建文件",
  Edit: "编辑文件",
  Bash: "运行命令",
  WebSearch: "搜索网页",
  WebFetch: "读取网页",
};

export function toolTitle(name: string) {
  if (toolTitles[name]) return toolTitles[name];
  if (name.endsWith("__tavily_search")) return "搜索网页";
  if (name.endsWith("__tavily_extract")) return "提取网页";
  return "调用工具";
}

const standaloneToolNames = new Set([
  "Task",
  "Agent",
  "harness_request_approval",
  "harness_present_artifact",
]);

export function completedToolBatch(view: RunViewModel | undefined) {
  return view?.tools.filter(
    (tool) => tool.status === "completed" && !standaloneToolNames.has(tool.name),
  ) ?? [];
}

function batchDigest(tools: readonly RunToolNode[]) {
  const counts = new Map<string, number>();
  for (const tool of tools) {
    const title = toolTitle(tool.name);
    counts.set(title, (counts.get(title) ?? 0) + 1);
  }
  return [...counts]
    .map(([title, count]) => count > 1 ? `${title} ×${count}` : title)
    .join(" · ");
}

function CompletedToolBatch({ tools }: { tools: readonly RunToolNode[] }) {
  return (
    <details className="tool-card tool-status-complete tool-card-batch">
      <summary>
        <span className="tool-glyph tool-batch-glyph" aria-hidden="true"><i /></span>
        <span className="tool-card-title">
          <strong>已处理 {tools.length} 个工具调用</strong>
          <small>{batchDigest(tools)}</small>
        </span>
        <span className="tool-status-label">已收起</span>
        <span className="tool-chevron" aria-hidden="true" />
      </summary>
      <div className="tool-batch-list">
        {tools.map((tool) => (
          <div className="tool-batch-row" key={tool.id}>
            <span>{toolTitle(tool.name)}</span>
            <code>{tool.name}</code>
            <small>已完成</small>
          </div>
        ))}
      </div>
    </details>
  );
}

export function ToolCard({
  toolCallId,
  name,
  status,
  args,
  result,
  isError = false,
}: {
  toolCallId?: string;
  name: string;
  status: ToolStatus;
  args: unknown;
  result?: unknown;
  isError?: boolean;
}) {
  const view = useRunViewModel();
  const batch = completedToolBatch(view);
  const batchIndex = toolCallId
    ? batch.findIndex((tool) => tool.id === toolCallId)
    : -1;

  if (!isError && status === "complete" && batch.length > 1 && batchIndex >= 0) {
    return batchIndex === 0 ? <CompletedToolBatch tools={batch} /> : null;
  }

  return (
    <details className={`tool-card tool-status-${status}`} open={status !== "complete"}>
      <summary>
        <span className="tool-glyph" aria-hidden="true"><i /></span>
        <span className="tool-card-title">
          <strong>{toolTitle(name)}</strong>
          <small>{name}</small>
        </span>
        <span className="tool-status-label">{statusLabel[status]}</span>
        <span className="tool-chevron" aria-hidden="true" />
      </summary>
      <div className="tool-card-body">
        <StructuredValue value={args} label="输入" />
        {result !== undefined && <StructuredValue value={result} label="输出" />}
      </div>
    </details>
  );
}
