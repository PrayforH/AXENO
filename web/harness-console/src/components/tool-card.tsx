import { StructuredValue } from "./structured-value";

type ToolStatus = "inProgress" | "executing" | "complete";

const statusLabel: Record<ToolStatus, string> = {
  inProgress: "准备中",
  executing: "执行中",
  complete: "已完成",
};

export function ToolCard({
  name,
  status,
  args,
  result,
}: {
  name: string;
  status: ToolStatus;
  args: unknown;
  result?: unknown;
}) {
  return (
    <details className={`tool-card tool-status-${status}`} open={status !== "complete"}>
      <summary>
        <span className="tool-glyph" aria-hidden="true">↗</span>
        <span className="tool-card-title">
          <strong>{name}</strong>
          <small>工具调用</small>
        </span>
        <span className="tool-status-label">{statusLabel[status]}</span>
      </summary>
      <div className="tool-card-body">
        <StructuredValue value={args} label="输入" />
        {result !== undefined && <StructuredValue value={result} label="输出" />}
      </div>
    </details>
  );
}
