"use client";

import { useRunViewModel } from "../../lib/activity-store";

function estimateTokens(text: string): number {
  return Math.ceil(text.length / 3.5);
}

export function TokenIndicator() {
  const runView = useRunViewModel();
  const tokens = runView?.items.filter(
    (item) =>
      item.event_type === "message.delta" || item.event_type === "message.start",
  ).length;

  if (!runView || runView.phase === "completed" || runView.phase === "failed" || runView.phase === "cancelled") {
    return null;
  }

  return (
    <div className="token-indicator" aria-label="Token 用量">
      <span className="token-bar">
        <span
          className="token-bar-fill"
          style={{ width: `${Math.min(tokens ? tokens * 2 : 0, 100)}%` }}
        />
      </span>
      <small>约 {tokens} tokens</small>
    </div>
  );
}
