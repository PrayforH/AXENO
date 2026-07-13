import { describe, expect, it } from "vitest";
import type { PendingAttachment } from "@assistant-ui/react";
import { createInputAttachmentAdapter } from "../src/lib/input-attachment-adapter";

describe("Harness input attachment adapter", () => {
  it("uploads once, then sends only the server-issued opaque id", async () => {
    let uploadedBody: FormData | undefined;
    const fetcher: typeof fetch = async (_input, init) => {
      uploadedBody = init?.body as FormData;
      return Response.json(
        {
          input_artifact_id: "input_artifact_abc123",
          name: "facts.txt",
          media_type: "text/plain",
          status: "ready",
          size_bytes: 18,
        },
        { status: 201 },
      );
    };
    const adapter = createInputAttachmentAdapter(fetcher);
    const file = new File(["local file content"], "facts.txt", {
      type: "text/plain",
    });

    const pending = (await adapter.add({ file })) as PendingAttachment;
    const complete = await adapter.send(pending);

    expect(uploadedBody?.get("file")).toBe(file);
    expect(pending).toMatchObject({
      id: "input_artifact_abc123",
      type: "document",
      name: "facts.txt",
      contentType: "text/plain",
      status: { type: "requires-action", reason: "composer-send" },
    });
    expect(complete.status).toEqual({ type: "complete" });
    expect(complete.content).toEqual([
      {
        type: "file",
        data: "input_artifact_abc123",
        mimeType: "text/plain",
        filename: "facts.txt",
      },
    ]);
    expect(JSON.stringify(complete)).not.toContain("local file content");
  });

  it("surfaces the Harness upload error instead of creating a broken attachment", async () => {
    const adapter = createInputAttachmentAdapter(async () =>
      Response.json(
        { error: { code: "input_artifact_too_large", message: "too large" } },
        { status: 413 },
      ),
    );

    await expect(
      adapter.add({
        file: new File(["large"], "large.bin", {
          type: "application/octet-stream",
        }),
      }),
    ).rejects.toThrow("too large");
  });
});
