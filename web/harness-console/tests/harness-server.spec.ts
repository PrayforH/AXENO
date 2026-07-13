import { describe, expect, it } from "vitest";
import { decideApproval, downloadArtifact } from "../src/lib/harness-server";

describe("Harness BFF requests", () => {
  it("sends an approval decision with server-side identity", async () => {
    let capturedUrl = "";
    let capturedInit: RequestInit | undefined;
    const fetcher: typeof fetch = async (input, init) => {
      capturedUrl = String(input);
      capturedInit = init;
      return new Response(JSON.stringify({ status: "approved" }), { status: 200 });
    };

    await decideApproval("approval/1", "approved", fetcher, {
      HARNESS_API_URL: "https://harness.internal/",
      HARNESS_TENANT_ID: "tenant-a",
      HARNESS_USER_ID: "user-1",
    });

    expect(capturedUrl).toBe(
      "https://harness.internal/v1/approvals/approval%2F1",
    );
    expect(capturedInit?.method).toBe("PUT");
    expect(capturedInit?.headers).toEqual({
      "Content-Type": "application/json",
      "X-Tenant-ID": "tenant-a",
      "X-User-ID": "user-1",
    });
    expect(capturedInit?.body).toBe(JSON.stringify({ decision: "approved" }));
  });

  it("downloads an artifact without exposing object-store coordinates", async () => {
    let capturedUrl = "";
    let capturedInit: RequestInit | undefined;
    const fetcher: typeof fetch = async (input, init) => {
      capturedUrl = String(input);
      capturedInit = init;
      return new Response("artifact", { status: 200 });
    };

    await downloadArtifact("artifact-1", fetcher, {
      HARNESS_API_URL: "https://harness.internal",
      HARNESS_TENANT_ID: "tenant-a",
      HARNESS_USER_ID: "user-1",
    });

    expect(capturedUrl).toBe(
      "https://harness.internal/v1/artifacts/artifact-1/content",
    );
    expect(capturedInit?.headers).toEqual({
      "X-Tenant-ID": "tenant-a",
      "X-User-ID": "user-1",
    });
    expect(capturedUrl).not.toContain("minio");
  });
});
