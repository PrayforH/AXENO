import { afterEach, describe, expect, it, vi } from "vitest";
import { DEFAULT_STUDIO_DRAFT } from "../src/lib/agent-studio";
import {
  apiDraftToStudioDraft,
  StudioApiError,
  studioClient,
  studioDraftToSpec,
  type ApiAgentDraft,
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
    expect(saved.skills[0].files).toEqual([
      { path: "references/rules.md", content: "rules" },
    ]);
    expect(saved.model.requiredCapabilities).toEqual(["streaming", "tool_use"]);
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
});
