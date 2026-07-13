import { decideApproval, type ApprovalDecision } from "../../../../../lib/harness-server";

const DECISIONS = new Set<ApprovalDecision>(["approved", "rejected"]);

export async function PUT(
  request: Request,
  context: { params: Promise<{ approvalId: string }> },
): Promise<Response> {
  const { approvalId } = await context.params;
  const body = (await request.json()) as { decision?: string };
  if (!body.decision || !DECISIONS.has(body.decision as ApprovalDecision)) {
    return Response.json(
      { error: { code: "invalid_decision", message: "请选择批准或拒绝。" } },
      { status: 422 },
    );
  }
  const upstream = await decideApproval(
    approvalId,
    body.decision as ApprovalDecision,
  );
  return new Response(await upstream.text(), {
    status: upstream.status,
    headers: {
      "Content-Type": upstream.headers.get("Content-Type") ?? "application/json",
    },
  });
}
