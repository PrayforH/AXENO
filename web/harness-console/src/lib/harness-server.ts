import {
  getHarnessServerConfig,
  type ServerEnvironment,
} from "./server-config";

export type ApprovalDecision = "approved" | "rejected";

export function decideApproval(
  approvalId: string,
  decision: ApprovalDecision,
  fetcher: typeof fetch = fetch,
  environment: ServerEnvironment = process.env,
): Promise<Response> {
  const config = getHarnessServerConfig(environment);
  return fetcher(
    `${config.apiUrl}/v1/approvals/${encodeURIComponent(approvalId)}`,
    {
      method: "PUT",
      headers: {
        "Content-Type": "application/json",
        ...config.identityHeaders,
        ...config.serviceHeaders,
      },
      body: JSON.stringify({ decision }),
    },
  );
}

export function downloadArtifact(
  artifactId: string,
  fetcher: typeof fetch = fetch,
  environment: ServerEnvironment = process.env,
): Promise<Response> {
  const config = getHarnessServerConfig(environment);
  return fetcher(
    `${config.apiUrl}/v1/artifacts/${encodeURIComponent(artifactId)}/content`,
    { headers: { ...config.identityHeaders, ...config.serviceHeaders } },
  );
}
