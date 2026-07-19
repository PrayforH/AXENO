import { afterEach, describe, expect, it, vi } from "vitest";
import {
  DEFAULT_STUDIO_DRAFT,
  evaluateStudioDraft,
} from "./agent-studio";
import {
  apiDraftToStudioDraft,
  studioClient,
  studioDraftToSpec,
  type StudioGovernedPolicy,
} from "./studio-client";

afterEach(() => {
  vi.restoreAllMocks();
});

describe("Studio knowledge reference contract", () => {
  it("round-trips knowledge references through the API draft shape", () => {
    const draft = {
      ...DEFAULT_STUDIO_DRAFT,
      knowledgeReferences: ["company-policy", "engineering-runbooks"],
    };
    const spec = studioDraftToSpec(draft);
    const apiDraft = {
      draftId: "draft-a",
      tenantId: "tenant-a",
      revision: 4,
      spec,
      publishedVersion: null,
      publishedHash: null,
      publishedPackageHash: null,
      createdBy: "owner-a",
      updatedBy: "owner-a",
      createdAt: "2026-07-19T00:00:00Z",
      updatedAt: "2026-07-19T00:00:00Z",
    } as unknown as Parameters<typeof apiDraftToStudioDraft>[0];

    expect(apiDraftToStudioDraft(apiDraft).knowledgeReferences).toEqual([
      "company-policy",
      "engineering-runbooks",
    ]);
  });

  it("treats an older API payload without the field as unbound", () => {
    const spec = studioDraftToSpec(DEFAULT_STUDIO_DRAFT);
    delete (spec as Partial<typeof spec>).knowledgeReferences;
    const apiDraft = {
      draftId: "draft-a",
      tenantId: "tenant-a",
      revision: 1,
      spec,
      publishedVersion: null,
      publishedHash: null,
      publishedPackageHash: null,
      createdBy: "owner-a",
      updatedBy: "owner-a",
      createdAt: "2026-07-19T00:00:00Z",
      updatedAt: "2026-07-19T00:00:00Z",
    } as unknown as Parameters<typeof apiDraftToStudioDraft>[0];

    expect(apiDraftToStudioDraft(apiDraft).knowledgeReferences).toEqual([]);
  });

  it("counts the platform knowledge tool only when a base is bound", () => {
    const baseline = evaluateStudioDraft(DEFAULT_STUDIO_DRAFT).toolCount;
    const withKnowledge = evaluateStudioDraft({
      ...DEFAULT_STUDIO_DRAFT,
      knowledgeReferences: ["company-policy"],
    }).toolCount;

    expect(withKnowledge).toBe(baseline + 1);
  });
});

describe("Studio governance request contract", () => {
  it("sends only an external secret reference when creating a connection", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ connectionId: "personal-search" }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );

    await studioClient.createConnection({
      connectionId: "personal-search",
      displayName: "个人搜索",
      resourceKind: "mcp",
      resourceReference: "search",
      scope: "personal",
      principalId: "user-a",
      secretReference: "settings://mcp/search",
      requiredKeys: ["api_key"],
    });

    const [, init] = fetchMock.mock.calls[0];
    const body = JSON.parse(String(init?.body)) as Record<string, unknown>;
    expect(body.secretReference).toBe("settings://mcp/search");
    expect(body).not.toHaveProperty("secretValue");
  });

  it("uses the current revision for policy publication", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ policyId: "local-standard" }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
    const policy = {
      policyId: "local-standard",
      revision: 9,
    } as StudioGovernedPolicy;

    await studioClient.publishGovernedPolicy(policy);

    const [, init] = fetchMock.mock.calls[0];
    expect(JSON.parse(String(init?.body))).toEqual({ expectedRevision: 9 });
  });
});
