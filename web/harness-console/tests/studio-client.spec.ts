import { afterEach, describe, expect, it, vi } from "vitest";
import { DEFAULT_STUDIO_DRAFT } from "../src/lib/agent-studio";
import {
  apiDraftToStudioDraft,
  StudioApiError,
  studioClient,
  studioDraftToSpec,
  type ApiAgentDraft,
  type StudioEnvironmentResourcePolicy,
} from "../src/lib/studio-client";

function apiDraft(): ApiAgentDraft {
  const spec = studioDraftToSpec({
    ...DEFAULT_STUDIO_DRAFT,
    id: "draft-api",
    revision: 3,
  });
  return {
    draftId: "draft-api",
    tenantId: "tenant-a",
    revision: 3,
    spec,
    createdBy: "builder-a",
    updatedBy: "builder-b",
    createdAt: "2026-07-16T00:00:00Z",
    updatedAt: "2026-07-16T00:01:00Z",
    publishedVersion: null,
    publishedHash: null,
    publishedPackageHash: null,
  };
}

function environmentPolicy(): StudioEnvironmentResourcePolicy {
  return {
    executionProfileId: "isolated-default",
    executionProfileVersion: 1,
    networkProfileId: "registered-mcp-only",
    networkProfileVersion: 1,
    networkAccess: ["none", "internal", "external"],
    allowedModelRoutes: ["new-api-default"],
    capabilityCatalogRevision: 1,
    allowedMcpReferences: ["tavily-readonly"],
    allowedKnowledgeReferences: [],
    credentialScopes: ["user", "team", "workload"],
    quota: {
      maxRunBudgetUsd: 1,
      maxModelTokens: 200_000,
      maxArtifactBytes: 26_214_400,
    },
  };
}

describe("Studio typed API mapping", () => {
  afterEach(() => vi.unstubAllGlobals());
  it("round-trips the editable server Draft without losing revision or files", () => {
    const source = apiDraft();
    source.spec.skills[0].files = [{ path: "references/rules.md", content: "rules" }];

    const draft = apiDraftToStudioDraft(source);
    const saved = studioDraftToSpec(draft);

    expect(draft.id).toBe("draft-api");
    expect(draft.revision).toBe(3);
    expect(draft.executionProfile).toBe("isolated-default");
    expect(draft.maxModelTokens).toBe(200000);
    expect(saved.skills[0].files).toEqual([
      { path: "references/rules.md", content: "rules" },
    ]);
    expect(saved.model.requiredCapabilities).toEqual(["streaming", "tool_use"]);
    expect(saved.limits.maxModelTokens).toBe(200000);
  });

  it("reads usage and replaces quota policy with revision CAS", async () => {
    const calls: Array<{ url: string; body: unknown }> = [];
    vi.stubGlobal("fetch", async (input: RequestInfo | URL, init?: RequestInit) => {
      calls.push({ url: String(input), body: init?.body ? JSON.parse(String(init.body)) : null });
      if (!init?.method) return Response.json({ policies: [], counters: [], activeReservations: [], unknownCostEntries: 0 });
      return Response.json({ policyId: "tenant-default", revision: 2 });
    });

    await studioClient.quotaUsage();
    await studioClient.replaceQuotaPolicy("tenant-default", 1, { concurrent_runs: 12 });

    expect(calls).toEqual([
      { url: "/api/studio/quotas", body: null },
      { url: "/api/studio/quotas/tenant-default", body: { expectedRevision: 1, scope: { agentName: null, environment: null }, limits: { concurrent_runs: 12 } } },
    ]);
  });

  it("maps server eval tags into the editor and restores them on save", () => {
    const source = apiDraft();
    source.spec.evaluationCases[0].tags = ["safety", "public-opinion"];

    const draft = apiDraftToStudioDraft(source);

    expect(draft.evalCases[0].tag).toBe("safety");
    expect(studioDraftToSpec(draft).evaluationCases[0].tags).toContain("safety");
  });

  it("preserves 409 as a typed revision conflict", async () => {
    vi.stubGlobal("fetch", async () => Response.json(
      { error: { code: "draft_conflict", message: "revision changed" } },
      { status: 409 },
    ));

    await expect(studioClient.replaceDraft(DEFAULT_STUDIO_DRAFT)).rejects.toMatchObject({
      status: 409,
      code: "draft_conflict",
    } satisfies Partial<StudioApiError>);
  });

  it("publishes the exact server revision and preserves a version conflict", async () => {
    const fetcher = vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
      expect(init?.method).toBe("POST");
      expect(JSON.parse(String(init?.body))).toEqual({ expectedRevision: 7 });
      return Response.json(
        { error: { code: "version_conflict", message: "immutable release exists" } },
        { status: 409 },
      );
    });
    vi.stubGlobal("fetch", fetcher);

    await expect(studioClient.publishDraft("draft-api", 7)).rejects.toMatchObject({
      status: 409,
      code: "version_conflict",
    } satisfies Partial<StudioApiError>);
    expect(fetcher).toHaveBeenCalledWith(
      "/api/studio/drafts/draft-api/publish",
      expect.objectContaining({ method: "POST" }),
    );
  });

  it("creates a Preview bound to the exact Draft revision and stable key", async () => {
    const fetcher = vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
      expect(init?.method).toBe("POST");
      expect(JSON.parse(String(init?.body))).toEqual({
        draftId: "draft-api",
        expectedRevision: 7,
        idempotencyKey: "preview:draft-api:r7:hash",
        ttlSeconds: 3600,
      });
      return Response.json({ previewId: "preview-one", status: "queued" });
    });
    vi.stubGlobal("fetch", fetcher);

    await studioClient.createPreview(
      "draft-api",
      7,
      "preview:draft-api:r7:hash",
    );

    expect(fetcher).toHaveBeenCalledWith(
      "/api/studio/previews",
      expect.objectContaining({ method: "POST" }),
    );
  });

  it("creates an immutable Dataset Version and a version-pinned Eval Run", async () => {
    const calls: Array<{ url: string; body: unknown }> = [];
    const fetcher = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      const body = init?.body ? JSON.parse(String(init.body)) : null;
      calls.push({ url, body });
      if (url.endsWith("eval-datasets")) {
        return Response.json({
          datasetId: "dataset-one",
          version: 2,
          agentName: "policy-researcher",
        });
      }
      return Response.json({ run: { evalRunId: "eval-one", status: "queued" } });
    });
    vi.stubGlobal("fetch", fetcher);

    const dataset = await studioClient.createEvalDataset(
      "draft-api",
      7,
      "发布必测集",
      "dataset-one",
    );
    await studioClient.createEvalRun(
      dataset,
      "1.2.3",
      "eval:dataset-one:v2:1.2.3",
      "preview-one",
    );

    expect(calls).toEqual([
      {
        url: "/api/studio/eval-datasets",
        body: {
          draftId: "draft-api",
          expectedRevision: 7,
          name: "发布必测集",
          datasetId: "dataset-one",
          required: true,
        },
      },
      {
        url: "/api/studio/eval-runs",
        body: {
          datasetId: "dataset-one",
          datasetVersion: 2,
          agentName: "policy-researcher",
          agentVersion: "1.2.3",
          idempotencyKey: "eval:dataset-one:v2:1.2.3",
          previewId: "preview-one",
        },
      },
    ]);
  });

  it("promotes with environment CAS and rolls back to a verified snapshot", async () => {
    const calls: Array<{ url: string; body: Record<string, unknown> }> = [];
    vi.stubGlobal("crypto", { randomUUID: () => "stable-operation" });
    vi.stubGlobal("fetch", async (input: RequestInfo | URL, init?: RequestInit) => {
      calls.push({
        url: String(input),
        body: JSON.parse(String(init?.body)) as Record<string, unknown>,
      });
      return Response.json({ deployment: { status: "queued" } });
    });
    const environment = {
      tenantId: "tenant-a",
      agentName: "policy-researcher",
      name: "production" as const,
      revision: 4,
      policyRevision: 2,
      policyHash: "f".repeat(64),
      resourcePolicy: environmentPolicy(),
      routes: [],
      healthySnapshotId: "snapshot-current",
      updatedAt: "2026-07-16T00:00:00Z",
    };

    await studioClient.promoteDeployment(
      "policy-researcher",
      "1.2.3",
      environment,
      "a".repeat(64),
      "isolated-default",
      10,
    );
    await studioClient.rollbackDeployment(
      "policy-researcher",
      environment,
      "snapshot-previous",
    );

    expect(calls[0]).toMatchObject({
      url: "/api/studio/deployments/promote",
      body: {
        agentName: "policy-researcher",
        agentVersion: "1.2.3",
        environment: "production",
        expectedEnvironmentRevision: 4,
        canaryPercent: 10,
        imageDigest: `sha256:${"a".repeat(64)}`,
      },
    });
    expect(calls[1]).toMatchObject({
      url: "/api/studio/agents/policy-researcher/environments/production/rollback",
      body: {
        snapshotId: "snapshot-previous",
        expectedEnvironmentRevision: 4,
      },
    });
  });

  it("rebases an Environment policy on the current catalog revision", async () => {
    const calls: Array<{ url: string; method: string; body: unknown }> = [];
    vi.stubGlobal("fetch", async (input: RequestInfo | URL, init?: RequestInit) => {
      calls.push({
        url: String(input),
        method: init?.method ?? "GET",
        body: init?.body ? JSON.parse(String(init.body)) : null,
      });
      if (!init?.method) {
        return Response.json({ revision: 7, catalog: {} });
      }
      return Response.json({ revision: 5, policyRevision: 3 });
    });
    const policy = environmentPolicy();
    const environment = {
      tenantId: "tenant-a",
      agentName: "policy-researcher",
      name: "production" as const,
      revision: 4,
      policyRevision: 2,
      policyHash: "f".repeat(64),
      resourcePolicy: policy,
      routes: [],
      healthySnapshotId: "snapshot-current",
      updatedAt: "2026-07-16T00:00:00Z",
    };

    await studioClient.replaceEnvironmentPolicy(
      "policy-researcher",
      environment,
      policy,
    );

    expect(calls).toEqual([
      { url: "/api/studio/catalog", method: "GET", body: null },
      {
        url: "/api/studio/agents/policy-researcher/environments/production/policy",
        method: "PUT",
        body: {
          expectedEnvironmentRevision: 4,
          policy: {
            ...policy,
            capabilityCatalogRevision: 7,
          },
        },
      },
    ]);
  });

  it("creates and rotates a revision-fenced external trigger", async () => {
    const calls: Array<{ url: string; body: unknown }> = [];
    vi.stubGlobal("fetch", async (input: RequestInfo | URL, init?: RequestInit) => {
      calls.push({
        url: String(input),
        body: init?.body ? JSON.parse(String(init.body)) : null,
      });
      return Response.json({
        trigger: {
          triggerId: "trigger-one",
          revision: calls.length,
          name: "Webhook",
          enabled: true,
        },
        secret: "one-time-secret",
      });
    });

    const created = await studioClient.createTrigger(
      "policy-researcher",
      "Webhook",
      "production",
    );
    await studioClient.rotateTriggerSecret({
      ...created.trigger,
      tenantId: "tenant-a",
      kind: "webhook",
      agentName: "policy-researcher",
      environment: "production",
      enabled: true,
      revision: 1,
      createdBy: "admin-a",
      createdAt: "2026-07-19T00:00:00Z",
      updatedAt: "2026-07-19T00:00:00Z",
      lastInvokedAt: null,
    });

    expect(calls).toEqual([
      {
        url: "/api/studio/agents/policy-researcher/triggers",
        body: { name: "Webhook", environment: "production" },
      },
      {
        url: "/api/studio/triggers/trigger-one/rotate-secret",
        body: { expectedRevision: 1 },
      },
    ]);
  });
});
