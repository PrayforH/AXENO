import { StructuredValue } from "./structured-value";

type ToolStatus = "inProgress" | "executing" | "complete";

interface SubagentCardProps {
  status: ToolStatus;
  parameters: Record<string, unknown>;
  result?: unknown;
}

const statusLabel: Record<ToolStatus, string> = {
  inProgress: "正在接收任务",
  executing: "执行中",
  complete: "已完成",
};

export function SubagentCard({ status, parameters, result }: SubagentCardProps) {
  const agent = String(parameters.subagent_type ?? parameters.agent ?? "helper");
  const description = parameters.description ?? parameters.prompt;
  return (
    <details className={`agent-card tool-status-${status}`} open={status !== "complete"}>
      <summary>
        <span className="agent-avatar" aria-hidden="true"><i /><i /></span>
        <span className="agent-card-copy">
          <strong>委派给 {agent}</strong>
          {description != null && <small>{String(description)}</small>}
        </span>
        <span className="tool-status-label">{statusLabel[status]}</span>
        <span className="tool-chevron" aria-hidden="true" />
      </summary>
      <div className="tool-card-body">
        <StructuredValue value={parameters} label="委派任务" />
        {result !== undefined && <StructuredValue value={result} label="子 Agent 结果" />}
      </div>
    </details>
  );
}
