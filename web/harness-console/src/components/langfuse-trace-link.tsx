"use client";

import { useRunActivity } from "../lib/activity-store";

export function LangfuseTraceLink() {
  const activity = useRunActivity();
  const search = new URLSearchParams();
  if (activity?.run_id) search.set("run_id", activity.run_id);
  if (activity?.trace_id) search.set("trace_id", activity.trace_id);
  const query = search.toString();
  const href = `/api/harness/observability${query ? `?${query}` : ""}`;

  return (
    <a
      className="icon-button langfuse-trace-link"
      href={href}
      target="_blank"
      rel="noreferrer"
      aria-label="在 Langfuse 查看运行 Trace"
      title={activity?.trace_id ? "打开本次运行的 Langfuse Trace" : "打开 Langfuse Trace 列表"}
    >
      <span className="langfuse-trace-glyph" aria-hidden="true">
        <i />
        <i />
        <i />
      </span>
      <span>Langfuse Trace</span>
      <span className="external-arrow" aria-hidden="true">↗</span>
    </a>
  );
}
