import { requireAuthenticatedResponse } from "./client-auth";
import type {
  BuiltinToolOption,
  McpOption,
  ModelRouteOption,
  StudioDraft,
  StudioEvalCase,
  StudioRisk,
} from "./agent-studio";

export type StudioRole = "owner" | "admin" | "member" | "viewer";

export type StudioDraftSummary = {
  draftId: string;
  name: string;
  displayName: string;
  domain: string;
  version: string;
  template: StudioDraft["template"];
  revision: number;
  updatedAt: string;
  publishedVersion: string | null;
};

type ApiEvalCase = {
  id: string;
  tags: string[];
  prompt: string;
  inputFiles: Array<{ path: string; mediaType: string }>;
  expect: StudioEvalCase["expect"];
};

type ApiDraftSpec = {
  name: string;
  version: string;
  displayName: string;
  description: string;
  domain: string;
  template: StudioDraft["template"];
  model: {
    routeId: string;
    model: string;
    fallbackRouteId: string | null;
    fallbackModel: string | null;
    requiredCapabilities: string[];
  };
  systemPrompt: string;
  skills: Array<{
    name: string;
    description: string;
    instructions: string;
    files: Array<{ path: string; content: string }>;
  }>;
  builtinTools: string[];
  mcpServers: string[];
  subagents: StudioDraft["subagents"];
  permissionPolicy: string;
  executionProfile: string;
  workspace: { restoreSession: boolean; archiveOnComplete: boolean };
  limits: { maxTurns: number; timeoutSeconds: number; maxBudgetUsd: number };
  evaluationCases: ApiEvalCase[];
};

export type ApiAgentDraft = {
  draftId: string;
  tenantId: string;
  revision: number;
  spec: ApiDraftSpec;
  createdBy: string;
  updatedBy: string;
  createdAt: string;
  updatedAt: string;
  publishedVersion: string | null;
  publishedHash: string | null;
  publishedPackageHash: string | null;
};

export type ApiAgentVersion = {
  tenant_id: string;
  name: string;
  version: string;
  status: "published";
  manifest_hash: string;
  package_hash: string | null;
  created_at: string;
};

export type StudioValidation = {
  ready: boolean;
  issues: Array<{ code: string; message: string; severity: "error" | "warning"; path: string | null }>;
  contentHash: string | null;
  packageHash: string | null;
};

export type StudioPreflightCheck = {
  stage: "bundle" | "sandbox_provision" | "sandbox_prepare" | "model" | "mcp" | "approval" | "workspace_artifact" | "cleanup";
  status: "passed" | "failed" | "skipped" | "cancelled" | "timed_out";
  startedAt: string;
  completedAt: string;
  durationMs: number;
  summary: string;
  errorCode: string | null;
  details: Record<string, string | number | boolean>;
};

export type StudioPreflightResult = {
  schemaVersion: "harness.preflight/v1";
  previewId: string;
  status: "passed" | "failed" | "cancelled" | "timed_out";
  startedAt: string;
  completedAt: string;
  checks: StudioPreflightCheck[];
  events: Array<{
    sequence: number;
    eventType: "check.started" | "check.completed";
    stage: StudioPreflightCheck["stage"];
    occurredAt: string;
    status: StudioPreflightCheck["status"] | null;
    errorCode: string | null;
  }>;
  errorCode: string | null;
  artifact: {
    name: string;
    mediaType: string;
    sha256: string;
    sizeBytes: number;
  } | null;
};

export type StudioPreview = {
  previewId: string;
  tenantId: string;
  draftId: string;
  draftRevision: number;
  contentHash: string;
  packageHash: string;
  requestedBy: string;
  idempotencyKey: string;
  status: "queued" | "provisioning" | "ready" | "cancelling" | "cancelled" | "failed" | "expired";
  identityKind: "test";
  environment: "preview";
  fencingToken: number;
  createdAt: string;
  updatedAt: string;
  expiresAt: string;
  errorCode: string | null;
  preflightResult: StudioPreflightResult | null;
  stale: boolean;
  staleReason: string | null;
};

export type StudioEvalDataset = {
  tenantId: string;
  datasetId: string;
  version: number;
  name: string;
  agentName: string;
  required: boolean;
  sourceDraftId: string;
  sourceDraftRevision: number;
  sourceContentHash: string;
  sourcePackageHash: string;
  cases: ApiEvalCase[];
  fixtures: Array<{
    path: string;
    mediaType: string;
    objectId: string;
    sha256: string;
    sizeBytes: number;
  }>;
  createdBy: string;
  createdAt: string;
};

export type StudioEvalCaseResult = {
  tenantId: string;
  evalRunId: string;
  caseId: string;
  sessionId: string;
  runId: string;
  status: "passed" | "failed" | "error" | "timed_out" | "cancelled";
  passed: boolean;
  durationSeconds: number;
  failures: string[];
  tools: string[];
  approvalRequested: boolean;
  completedAt: string;
};

export type StudioEvalRun = {
  run: {
    tenantId: string;
    evalRunId: string;
    datasetId: string;
    datasetVersion: number;
    agentName: string;
    agentVersion: string;
    previewId: string | null;
    environment: string | null;
    requestedBy: string;
    idempotencyKey: string;
    status: "queued" | "running" | "cancelling" | "cancelled" | "passed" | "failed";
    fencingToken: number;
    nextCaseIndex: number;
    activeCaseId: string | null;
    activeSessionId: string | null;
    activeInputArtifactIds: string[];
    activeRunId: string | null;
    activeStartedAt: string | null;
    createdAt: string;
    updatedAt: string;
    completedAt: string | null;
    errorCode: string | null;
    artifacts: Array<{
      artifactId: string;
      name: string;
      mediaType: string;
      sha256: string;
      sizeBytes: number;
    }>;
  };
  cases: StudioEvalCaseResult[];
  passedCases: number;
  totalCases: number;
};

export type StudioEvalGate = {
  agentName: string;
  agentVersion: string;
  passed: boolean;
  requiredDatasets: number;
  passedDatasets: number;
  missingDatasetIds: string[];
};

export type StudioEnvironmentName = "test" | "canary" | "production";

export type StudioEnvironment = {
  tenantId: string;
  agentName: string;
  name: StudioEnvironmentName;
  revision: number;
  routes: Array<{ snapshotId: string; weight: number }>;
  healthySnapshotId: string | null;
  updatedAt: string;
};

export type StudioDeploymentSnapshot = {
  tenantId: string;
  snapshotId: string;
  agentName: string;
  agentVersion: string;
  environment: StudioEnvironmentName;
  manifestHash: string;
  packageHash: string;
  imageDigest: string;
  executionProfile: string;
  config: Record<string, string | number | boolean>;
  evalGatePassed: boolean;
  evalRequiredDatasets: number;
  previewId: string | null;
  createdBy: string;
  createdAt: string;
};

export type StudioDeployment = {
  deployment: {
    tenantId: string;
    deploymentId: string;
    agentName: string;
    environment: StudioEnvironmentName;
    action: "promote" | "rollback";
    targetSnapshotId: string;
    previousSnapshotId: string | null;
    canaryPercent: number;
    expectedEnvironmentRevision: number;
    idempotencyKey: string;
    requestedBy: string;
    status: "queued" | "reconciling" | "succeeded" | "failed";
    fencingToken: number;
    createdAt: string;
    updatedAt: string;
    completedAt: string | null;
    errorCode: string | null;
  };
  target: StudioDeploymentSnapshot;
  environment: StudioEnvironment;
};

export type StudioCapabilities = {
  modelRoutes: Array<{
    routeId: string;
    label: string;
    provider: string;
    models: string[];
    capabilities: string[];
    enabled: boolean;
  }>;
  builtinTools: Array<{
    name: string;
    label: string;
    description: string;
    risk: StudioRisk;
    approvalBehavior: string;
  }>;
  mcpServers: Array<{
    reference: string;
    label: string;
    description: string;
    tools: string[];
    risk: StudioRisk;
    networkAccess: McpOption["network"];
    sendsUserData: boolean;
    enabled: boolean;
  }>;
  policies: Array<{ policyId: string; label: string; description: string; enabled: boolean }>;
};

export class StudioApiError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    message: string,
  ) {
    super(message);
    this.name = "StudioApiError";
  }
}

async function errorFrom(response: Response): Promise<StudioApiError> {
  let code = `http_${response.status}`;
  let message = `请求失败（${response.status}）`;
  try {
    const payload = (await response.json()) as {
      error?: { code?: string; message?: string };
    };
    code = payload.error?.code ?? code;
    message = payload.error?.message ?? message;
  } catch {}
  return new StudioApiError(response.status, code, message);
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = requireAuthenticatedResponse(
    await fetch(`/api/studio/${path.replace(/^\//, "")}`, {
      ...init,
      cache: "no-store",
      headers: {
        ...(init.body ? { "Content-Type": "application/json" } : {}),
        ...init.headers,
      },
    }),
  );
  if (!response.ok) throw await errorFrom(response);
  return response.json() as Promise<T>;
}

export function apiDraftToStudioDraft(source: ApiAgentDraft): StudioDraft {
  const spec = source.spec;
  return {
    id: source.draftId,
    revision: source.revision,
    publishedVersion: source.publishedVersion,
    publishedHash: source.publishedHash,
    publishedPackageHash: source.publishedPackageHash,
    displayName: spec.displayName,
    name: spec.name,
    description: spec.description,
    domain: spec.domain,
    version: spec.version,
    template: spec.template,
    modelRoute: spec.model.routeId,
    model: spec.model.model,
    requiredCapabilities: spec.model.requiredCapabilities,
    systemPrompt: spec.systemPrompt,
    skills: spec.skills,
    builtinTools: spec.builtinTools,
    mcpServers: spec.mcpServers,
    subagents: spec.subagents,
    policy: spec.permissionPolicy,
    executionProfile: spec.executionProfile,
    restoreSession: spec.workspace.restoreSession,
    archiveOnComplete: spec.workspace.archiveOnComplete,
    maxTurns: spec.limits.maxTurns,
    timeoutSeconds: spec.limits.timeoutSeconds,
    maxBudgetUsd: spec.limits.maxBudgetUsd,
    evalCases: spec.evaluationCases.map((item) => ({
      id: item.id,
      label: item.id,
      tag: (item.tags.find((tag) => ["happy", "ambiguous", "safety"].includes(tag)) ?? "happy") as StudioEvalCase["tag"],
      prompt: item.prompt,
      expect: item.expect,
    })),
  };
}

export function studioDraftToSpec(draft: StudioDraft): ApiDraftSpec {
  return {
    name: draft.name,
    version: draft.version,
    displayName: draft.displayName,
    description: draft.description,
    domain: draft.domain,
    template: draft.template,
    model: {
      routeId: draft.modelRoute,
      model: draft.model,
      fallbackRouteId: null,
      fallbackModel: null,
      requiredCapabilities: draft.requiredCapabilities,
    },
    systemPrompt: draft.systemPrompt,
    skills: draft.skills.map((skill) => ({ ...skill, files: skill.files ?? [] })),
    builtinTools: draft.builtinTools,
    mcpServers: draft.mcpServers,
    subagents: draft.subagents,
    permissionPolicy: draft.policy,
    executionProfile: draft.executionProfile,
    workspace: {
      restoreSession: draft.restoreSession,
      archiveOnComplete: draft.archiveOnComplete,
    },
    limits: {
      maxTurns: draft.maxTurns,
      timeoutSeconds: draft.timeoutSeconds,
      maxBudgetUsd: draft.maxBudgetUsd,
    },
    evaluationCases: draft.evalCases.map((item) => ({
      id: item.id,
      tags: [item.tag, draft.domain],
      prompt: item.prompt,
      inputFiles: [],
      expect: item.expect,
    })),
  };
}

export const studioClient = {
  listDrafts: () => request<StudioDraftSummary[]>("drafts"),
  getDraft: (draftId: string) =>
    request<ApiAgentDraft>(`drafts/${encodeURIComponent(draftId)}`),
  capabilities: () => request<StudioCapabilities>("capabilities"),
  createDraft: (draft: StudioDraft) =>
    request<ApiAgentDraft>("drafts", {
      method: "POST",
      body: JSON.stringify({
        name: draft.name,
        domain: draft.domain,
        displayName: draft.displayName,
        description: draft.description,
        template: draft.template,
      }),
    }),
  replaceDraft: (draft: StudioDraft) =>
    request<ApiAgentDraft>(`drafts/${encodeURIComponent(draft.id)}`, {
      method: "PUT",
      body: JSON.stringify({
        expectedRevision: draft.revision,
        spec: studioDraftToSpec(draft),
      }),
    }),
  validateDraft: (draftId: string) =>
    request<StudioValidation>(`drafts/${encodeURIComponent(draftId)}/validate`, {
      method: "POST",
    }),
  publishDraft: (draftId: string, expectedRevision: number) =>
    request<ApiAgentVersion>(`drafts/${encodeURIComponent(draftId)}/publish`, {
      method: "POST",
      body: JSON.stringify({ expectedRevision }),
    }),
  listPreviews: () => request<StudioPreview[]>("previews"),
  createPreview: (
    draftId: string,
    expectedRevision: number,
    idempotencyKey: string,
  ) => request<StudioPreview>("previews", {
    method: "POST",
    body: JSON.stringify({
      draftId,
      expectedRevision,
      idempotencyKey,
      ttlSeconds: 3600,
    }),
  }),
  getPreview: (previewId: string) =>
    request<StudioPreview>(`previews/${encodeURIComponent(previewId)}`),
  cancelPreview: (previewId: string) =>
    request<StudioPreview>(`previews/${encodeURIComponent(previewId)}/cancel`, {
      method: "POST",
    }),
  listEvalDatasets: () => request<StudioEvalDataset[]>("eval-datasets"),
  createEvalDataset: (
    draftId: string,
    expectedRevision: number,
    name: string,
    datasetId?: string,
  ) => request<StudioEvalDataset>("eval-datasets", {
    method: "POST",
    body: JSON.stringify({
      draftId,
      expectedRevision,
      name,
      ...(datasetId ? { datasetId } : {}),
      required: true,
    }),
  }),
  listEvalRuns: () => request<StudioEvalRun[]>("eval-runs"),
  createEvalRun: (
    dataset: StudioEvalDataset,
    agentVersion: string,
    idempotencyKey: string,
    previewId?: string,
  ) => request<StudioEvalRun>("eval-runs", {
    method: "POST",
    body: JSON.stringify({
      datasetId: dataset.datasetId,
      datasetVersion: dataset.version,
      agentName: dataset.agentName,
      agentVersion,
      idempotencyKey,
      ...(previewId ? { previewId } : {}),
    }),
  }),
  getEvalRun: (evalRunId: string) =>
    request<StudioEvalRun>(`eval-runs/${encodeURIComponent(evalRunId)}`),
  cancelEvalRun: (evalRunId: string) =>
    request<StudioEvalRun>(`eval-runs/${encodeURIComponent(evalRunId)}/cancel`, {
      method: "POST",
    }),
  getEvalGate: (agentName: string, agentVersion: string) =>
    request<StudioEvalGate>(
      `evaluation-gates/${encodeURIComponent(agentName)}/versions/${encodeURIComponent(agentVersion)}`,
    ),
  listEnvironments: (agentName: string) =>
    request<StudioEnvironment[]>(
      `agents/${encodeURIComponent(agentName)}/environments`,
    ),
  listDeployments: (agentName: string) =>
    request<StudioDeployment[]>(
      `agents/${encodeURIComponent(agentName)}/deployments`,
    ),
  listDeploymentSnapshots: (agentName: string) =>
    request<StudioDeploymentSnapshot[]>(
      `agents/${encodeURIComponent(agentName)}/deployment-snapshots`,
    ),
  promoteDeployment: (
    agentName: string,
    agentVersion: string,
    environment: StudioEnvironment,
    packageHash: string,
    executionProfile: string,
    canaryPercent: number,
  ) => request<StudioDeployment>("deployments/promote", {
    method: "POST",
    body: JSON.stringify({
      agentName,
      agentVersion,
      environment: environment.name,
      expectedEnvironmentRevision: environment.revision,
      canaryPercent,
      imageDigest: `sha256:${packageHash}`,
      executionProfile,
      config: {},
      idempotencyKey: `studio-deploy:${agentName}:${agentVersion}:${environment.name}:r${environment.revision}:${crypto.randomUUID()}`,
    }),
  }),
  rollbackDeployment: (
    agentName: string,
    environment: StudioEnvironment,
    snapshotId: string,
  ) => request<StudioDeployment>(
    `agents/${encodeURIComponent(agentName)}/environments/${environment.name}/rollback`,
    {
      method: "POST",
      body: JSON.stringify({
        snapshotId,
        expectedEnvironmentRevision: environment.revision,
        idempotencyKey: `studio-rollback:${agentName}:${environment.name}:${snapshotId}:r${environment.revision}:${crypto.randomUUID()}`,
      }),
    },
  ),
  async downloadEvalArtifact(evalRunId: string, artifactId: string): Promise<void> {
    const response = requireAuthenticatedResponse(
      await fetch(
        `/api/studio/eval-runs/${encodeURIComponent(evalRunId)}/artifacts/${encodeURIComponent(artifactId)}`,
        { cache: "no-store" },
      ),
    );
    if (!response.ok) throw await errorFrom(response);
    const disposition = response.headers.get("content-disposition") ?? "";
    const filename = /filename="([^"]+)"/.exec(disposition)?.[1] ?? "eval-report";
    const url = URL.createObjectURL(await response.blob());
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = filename;
    anchor.click();
    URL.revokeObjectURL(url);
  },
  async downloadBundle(draftId: string): Promise<void> {
    const response = requireAuthenticatedResponse(
      await fetch(`/api/studio/drafts/${encodeURIComponent(draftId)}/bundle`, {
        cache: "no-store",
      }),
    );
    if (!response.ok) throw await errorFrom(response);
    const disposition = response.headers.get("content-disposition") ?? "";
    const filename = /filename="([^"]+)"/.exec(disposition)?.[1] ?? "agent-bundle.zip";
    const url = URL.createObjectURL(await response.blob());
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = filename;
    anchor.click();
    URL.revokeObjectURL(url);
  },
};

export function capabilityOptions(catalog: StudioCapabilities): {
  routes: ModelRouteOption[];
  tools: BuiltinToolOption[];
  mcp: McpOption[];
} {
  return {
    routes: catalog.modelRoutes.filter((item) => item.enabled).map((item) => ({
      id: item.routeId,
      label: item.label,
      provider: item.provider,
      models: item.models,
      capabilities: item.capabilities,
    })),
    tools: catalog.builtinTools.map((item) => ({
      id: item.name,
      label: item.label,
      description: item.description,
      risk: item.risk,
      approval: item.approvalBehavior,
    })),
    mcp: catalog.mcpServers.filter((item) => item.enabled).map((item) => ({
      id: item.reference,
      label: item.label,
      description: item.description,
      tools: item.tools,
      network: item.networkAccess,
      sendsUserData: item.sendsUserData,
    })),
  };
}
