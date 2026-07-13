"use client";

import { useState } from "react";
import type { ApprovalDecision } from "../lib/harness-server";

export interface ApprovalDetails {
  approval_id: string;
  run_id: string;
  tool_call_id?: string;
  reason?: string;
  expires_at?: string;
}

export function approvalLabel(status: string) {
  return status === "pending" ? "等待人工审批" : status;
}

export function formatApprovalReason(reason?: string) {
  return reason?.trim() || "此操作需要你确认后才能继续。";
}

export function ApprovalCard({
  details,
  complete,
  onDecision,
}: {
  details: ApprovalDetails;
  complete: boolean;
  onDecision: (value: ApprovalDecision) => Promise<void>;
}) {
  const [pending, setPending] = useState<ApprovalDecision | null>(null);
  const [decision, setDecision] = useState<ApprovalDecision | null>(null);
  const [error, setError] = useState("");

  async function decide(value: ApprovalDecision) {
    setError("");
    setPending(value);
    try {
      await onDecision(value);
      setDecision(value);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setPending(null);
    }
  }

  const settled = complete || decision !== null;
  return (
    <section className="domain-card approval-domain-card" aria-live="polite">
      <div className="domain-card-kicker">
        <span className="domain-card-icon" aria-hidden="true">
          !
        </span>
        <span>{settled ? "审批已处理" : approvalLabel("pending")}</span>
      </div>
      <h3>允许 Agent 执行受保护操作？</h3>
      <p>{formatApprovalReason(details.reason)}</p>
      <dl className="domain-metadata">
        <div>
          <dt>工具调用</dt>
          <dd>{details.tool_call_id || "未提供"}</dd>
        </div>
        <div>
          <dt>Run</dt>
          <dd>{details.run_id}</dd>
        </div>
      </dl>
      {error && <p className="domain-error">{error}</p>}
      <div className="domain-actions">
        <button
          className="approve-button"
          type="button"
          disabled={settled || pending !== null}
          onClick={() => void decide("approved")}
        >
          {pending === "approved" ? "正在批准…" : "批准并继续"}
        </button>
        <button
          className="reject-button"
          type="button"
          disabled={settled || pending !== null}
          onClick={() => void decide("rejected")}
        >
          {pending === "rejected" ? "正在拒绝…" : "拒绝"}
        </button>
        {decision && (
          <span className="decision-label">
            {decision === "approved" ? "已批准，Run 正在恢复" : "已拒绝"}
          </span>
        )}
      </div>
    </section>
  );
}
