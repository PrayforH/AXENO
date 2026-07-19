import { describe, expect, it } from "vitest";
import {
  DEFAULT_STUDIO_DRAFT,
  evaluateStudioDraft,
} from "./agent-studio";
import {
  apiDraftToStudioDraft,
  studioDraftToSpec,
} from "./studio-client";

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
