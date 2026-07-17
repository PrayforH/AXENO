import { describe, expect, it } from "vitest";
import {
  decideApproval,
  downloadArtifact,
  downloadInputArtifact,
} from "../src/lib/harness-server";

describe("Harness BFF requests", () => {
  it("sends an approval decision with server-side identity", async () => {
    let capturedUrl = "";
    let capturedInit: RequestInit | undefined;
    const fetcher: typeof fetch = async (input, init) => {
      capturedUrl = String(input);
      capturedInit = init;
      return new Response(JSON.stringify({ status: "approved" }), { status: 200 });
    };

    const request = new Request("https://console.test/api/approval", {
      headers: { Cookie: "harness_access_token=user-jwt" },
    });
    await decideApproval("approval/1", "approved", request, fetcher, {
      HARNESS_API_URL: "https://harness.internal/",
      HARNESS_API_BEARER_TOKEN: "service-token",
    });

    expect(capturedUrl).toBe(
      "https://harness.internal/v1/approvals/approval%2F1",
    );
    expect(capturedInit?.method).toBe("PUT");
    const headers = new Headers(capturedInit?.headers);
    expect(headers.get("Content-Type")).toBe("application/json");
    expect(headers.get("Authorization")).toBe("Bearer user-jwt");
    expect(headers.get("X-Harness-Service-Token")).toBe("service-token");
    expect(headers.get("X-Tenant-ID")).toBeNull();
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

    const request = new Request("https://console.test/api/artifact", {
      headers: { Cookie: "harness_access_token=user-jwt" },
    });
    await downloadArtifact("artifact-1", request, fetcher, {
      HARNESS_API_URL: "https://harness.internal",
      HARNESS_API_BEARER_TOKEN: "service-token",
    });

    expect(capturedUrl).toBe(
      "https://harness.internal/v1/artifacts/artifact-1/content",
    );
    const headers = new Headers(capturedInit?.headers);
    expect(headers.get("Authorization")).toBe("Bearer user-jwt");
    expect(headers.get("X-Harness-Service-Token")).toBe("service-token");
    expect(headers.get("X-User-ID")).toBeNull();
    expect(capturedUrl).not.toContain("minio");
  });

  it("downloads a user input attachment through the authenticated BFF", async () => {
    let capturedUrl = "";
    const request = new Request("https://console.test/api/input", {
      headers: { Cookie: "harness_access_token=user-jwt" },
    });
    await downloadInputArtifact(
      "input_artifact_1",
      request,
      async (input) => {
        capturedUrl = String(input);
        return new Response("ppt", { status: 200 });
      },
      {
        HARNESS_API_URL: "https://harness.internal",
        HARNESS_API_BEARER_TOKEN: "service-token",
      },
    );

    expect(capturedUrl).toBe(
      "https://harness.internal/v1/input-artifacts/input_artifact_1/content",
    );
  });
});
