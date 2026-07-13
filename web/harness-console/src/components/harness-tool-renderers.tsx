"use client";

import {
  useDefaultRenderTool,
  useRenderTool,
} from "@copilotkit/react-core/v2";
import { z } from "zod";
import { ApprovalCard, type ApprovalDetails } from "./approval-card";
import { ArtifactCard, type ArtifactDetails } from "./artifact-list";

const approvalSchema = z.object({
  approval_id: z.string(),
  run_id: z.string(),
  tool_call_id: z.string().optional(),
  reason: z.string().optional(),
  expires_at: z.string().optional(),
  status: z.string().optional(),
});

const artifactSchema = z.object({
  artifact_id: z.string(),
  run_id: z.string(),
  name: z.string().optional(),
  media_type: z.string().optional(),
  size_bytes: z.number().optional(),
  sha256: z.string().optional(),
  status: z.string().optional(),
});

export function HarnessToolRenderers() {
  useRenderTool({
    agentId: "harness-agent",
    name: "harness_request_approval",
    parameters: approvalSchema,
    render: ({ status, parameters }) => {
      if (
        status === "inProgress" ||
        !parameters.approval_id ||
        !parameters.run_id
      ) {
        return <div className="domain-card domain-loading">正在准备审批信息…</div>;
      }
      return (
        <ApprovalCard
          details={parameters as ApprovalDetails}
          complete={status === "complete"}
          onDecision={async (decision) => {
            const response = await fetch(
              `/api/harness/approvals/${encodeURIComponent(parameters.approval_id)}`,
              {
                method: "PUT",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ decision }),
              },
            );
            if (!response.ok) {
              throw new Error((await response.text()) || `审批失败 (${response.status})`);
            }
          }}
        />
      );
    },
  });

  useRenderTool({
    agentId: "harness-agent",
    name: "harness_present_artifact",
    parameters: artifactSchema,
    render: ({ status, parameters }) => {
      if (
        status === "inProgress" ||
        !parameters.artifact_id ||
        !parameters.run_id
      ) {
        return <div className="domain-card domain-loading">正在登记运行产物…</div>;
      }
      return <ArtifactCard details={parameters as ArtifactDetails} />;
    },
  });

  useDefaultRenderTool();
  return null;
}
