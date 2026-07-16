import { restoreStudioDraft, type StudioDraft } from "./agent-studio";
import {
  apiDraftToStudioDraft,
  type ApiAgentDraft,
} from "./studio-client";

export const LEGACY_STUDIO_DRAFT_KEY = "harness-agent-studio-draft";
export const LEGACY_STUDIO_MIGRATION_KEY =
  "harness-agent-studio-draft-migrated-v1";

type MigrationClient = {
  getDraft(draftId: string): Promise<ApiAgentDraft>;
  createDraft(draft: StudioDraft): Promise<ApiAgentDraft>;
  replaceDraft(draft: StudioDraft): Promise<ApiAgentDraft>;
};

export type LegacyMigrationResult =
  | { status: "none" | "already-migrated" | "discarded"; draft: null }
  | { status: "imported"; draft: StudioDraft };

export async function migrateLegacyStudioDraft(
  storage: Pick<Storage, "getItem" | "setItem" | "removeItem">,
  client: MigrationClient,
  canEdit: boolean,
): Promise<LegacyMigrationResult> {
  if (!canEdit) return { status: "none", draft: null };
  const marker = storage.getItem(LEGACY_STUDIO_MIGRATION_KEY);
  if (marker && !marker.startsWith("pending:")) {
    return { status: "already-migrated", draft: null };
  }
  const serialized = storage.getItem(LEGACY_STUDIO_DRAFT_KEY);
  if (!serialized) return { status: "none", draft: null };

  let recovered: StudioDraft | null = null;
  try {
    recovered = restoreStudioDraft(JSON.parse(serialized));
  } catch {}
  if (!recovered) {
    storage.removeItem(LEGACY_STUDIO_DRAFT_KEY);
    storage.setItem(LEGACY_STUDIO_MIGRATION_KEY, "discarded-invalid");
    return { status: "discarded", draft: null };
  }

  // Persist the created id before replacing the complete spec. If the second request
  // fails (or its response is lost), the next reload resumes the same server draft
  // instead of creating a duplicate.
  const pendingDraftId = marker?.startsWith("pending:")
    ? marker.slice("pending:".length)
    : null;
  const created = pendingDraftId
    ? await client.getDraft(pendingDraftId)
    : await client.createDraft(recovered);
  if (!pendingDraftId) {
    storage.setItem(LEGACY_STUDIO_MIGRATION_KEY, `pending:${created.draftId}`);
  }
  const imported = await client.replaceDraft({
    ...recovered,
    id: created.draftId,
    revision: created.revision,
  });
  storage.removeItem(LEGACY_STUDIO_DRAFT_KEY);
  storage.setItem(LEGACY_STUDIO_MIGRATION_KEY, imported.draftId);
  return { status: "imported", draft: apiDraftToStudioDraft(imported) };
}
