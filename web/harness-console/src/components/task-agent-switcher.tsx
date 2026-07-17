"use client";

import {
  agentCoordinate,
  type TaskAgent,
} from "../lib/task-agent-catalog";

export function TaskAgentSwitcher({
  agents,
  selected,
  loading,
  onChange,
}: {
  agents: readonly TaskAgent[];
  selected: TaskAgent | null;
  loading: boolean;
  onChange: (agent: TaskAgent) => void;
}) {
  const coordinate = selected ? agentCoordinate(selected) : "";
  return (
    <label className="task-agent-switcher" htmlFor="task-agent-select">
      <span className="task-agent-switcher-mark" aria-hidden="true">
        <i />
        <i />
      </span>
      <span className="task-agent-switcher-copy">
        <small>当前智能体</small>
        <strong>{selected?.displayName ?? (loading ? "正在读取…" : "暂无可用版本")}</strong>
      </span>
      <select
        id="task-agent-select"
        value={coordinate}
        disabled={loading || agents.length === 0}
        aria-label="切换任务智能体；切换后创建新任务"
        title="切换智能体会创建一个新任务，历史任务仍使用原版本"
        onChange={(event) => {
          const next = agents.find(
            (agent) => agentCoordinate(agent) === event.target.value,
          );
          if (next) onChange(next);
        }}
      >
        {agents.map((agent) => (
          <option key={agentCoordinate(agent)} value={agentCoordinate(agent)}>
            {agent.displayName} · {agent.version}
          </option>
        ))}
      </select>
      <span className="task-agent-switcher-chevron" aria-hidden="true" />
    </label>
  );
}
