import type {
  AttachmentAdapter,
  CompleteAttachment,
  PendingAttachment,
} from "@assistant-ui/react";

interface InputArtifactUpload {
  input_artifact_id: string;
  name: string;
  media_type: string;
  status: "ready";
  size_bytes: number;
}

function isUpload(value: unknown): value is InputArtifactUpload {
  if (!value || typeof value !== "object") return false;
  const upload = value as Record<string, unknown>;
  return (
    typeof upload.input_artifact_id === "string" &&
    typeof upload.name === "string" &&
    typeof upload.media_type === "string" &&
    upload.status === "ready" &&
    typeof upload.size_bytes === "number"
  );
}

function errorMessage(value: unknown, fallback: string) {
  if (!value || typeof value !== "object") return fallback;
  const error = (value as Record<string, unknown>).error;
  if (!error || typeof error !== "object") return fallback;
  const message = (error as Record<string, unknown>).message;
  return typeof message === "string" ? message : fallback;
}

export function createInputAttachmentAdapter(
  fetcher: typeof fetch = fetch,
): AttachmentAdapter {
  return {
    accept: "*/*",
    async add({ file }): Promise<PendingAttachment> {
      const form = new FormData();
      form.append("file", file);
      const response = await fetcher("/api/input-artifacts", {
        method: "POST",
        body: form,
      });
      const payload: unknown = await response.json().catch(() => null);
      if (!response.ok || !isUpload(payload)) {
        throw new Error(
          errorMessage(payload, `附件上传失败（HTTP ${response.status}）`),
        );
      }
      return {
        id: payload.input_artifact_id,
        type: "document",
        name: payload.name,
        contentType: payload.media_type,
        file,
        status: { type: "requires-action", reason: "composer-send" },
      };
    },
    async send(attachment): Promise<CompleteAttachment> {
      const mimeType =
        attachment.contentType || attachment.file.type || "application/octet-stream";
      return {
        id: attachment.id,
        type: attachment.type,
        name: attachment.name,
        contentType: mimeType,
        status: { type: "complete" },
        content: [
          {
            type: "file",
            data: attachment.id,
            mimeType,
            filename: attachment.name,
          },
        ],
      };
    },
    async remove() {
      // Unbound uploads are reclaimed by the input-artifact lifecycle later.
    },
  };
}
