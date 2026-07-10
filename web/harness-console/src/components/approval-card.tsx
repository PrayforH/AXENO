export function approvalLabel(status: string) { return status === "pending" ? "等待人工审批" : status; }
export function ApprovalCard({ id, onDecision }: { id: string; onDecision: (value: "approved" | "rejected") => void }) {
  return <div className="card"><strong>{approvalLabel("pending")}</strong><p className="muted">{id}</p><div className="row"><button onClick={() => onDecision("approved")}>批准</button><button className="danger" onClick={() => onDecision("rejected")}>拒绝</button></div></div>;
}

