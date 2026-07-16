import { describe, expect, it } from "vitest";
import {
  proxyAguiRequest,
  proxyDataLifecycleRequest,
  proxyInputArtifactRequest,
  proxyStudioRequest,
} from "../src/lib/harness-proxy";
import type { HarnessServerConfig } from "../src/lib/server-config";

const config: HarnessServerConfig = {
  apiUrl: "http://harness.internal:8000",
  agentName: "echo-agent",
  agentVersion: "0.1.0",
  aguiUrl:
    "http://harness.internal:8000/v1/agui?agent_name=echo-agent&agent_version=0.1.0",
  serviceHeaders: {
    "X-Harness-Service-Token": "server-only-token",
  },
  cookieSecure: false,
  refreshCookieDays: 30,
  googleClientId: "",
  githubClientId: "",
  publicUrl: "",
};

describe("Harness same-origin proxies", () => {
  it("injects server-only identity and preserves the AG-UI response stream", async () => {
    let upstreamUrl = "";
    let upstreamInit: RequestInit | undefined;
    const fetcher: typeof fetch = async (input, init) => {
      upstreamUrl = String(input);
      upstreamInit = init;
      const encoder = new TextEncoder();
      return new Response(
        new ReadableStream({
          start(controller) {
            controller.enqueue(encoder.encode("data: first\n\n"));
            controller.enqueue(encoder.encode("data: second\n\n"));
            controller.close();
          },
        }),
        { status: 200, headers: { "Content-Type": "text/event-stream" } },
      );
    };
    const request = new Request("http://console.test/api/agui", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Cookie: "private=browser; harness_access_token=user-jwt",
      },
      body: JSON.stringify({ threadId: "thread-1" }),
    });

    const response = await proxyAguiRequest(request, config, fetcher);

    expect(upstreamUrl).toBe(config.aguiUrl);
    const headers = new Headers(upstreamInit?.headers);
    expect(headers.get("X-Tenant-ID")).toBeNull();
    expect(headers.get("X-User-ID")).toBeNull();
    expect(headers.get("Authorization")).toBe("Bearer user-jwt");
    expect(headers.get("X-Harness-Service-Token")).toBe("server-only-token");
    expect(headers.get("Cookie")).toBeNull();
    expect(headers.get("Content-Type")).toBe("application/json");
    expect(response.headers.get("Content-Type")).toBe("text/event-stream");
    expect(await response.text()).toBe("data: first\n\ndata: second\n\n");
  });

  it("routes cancellation through the same identity boundary", async () => {
    let upstreamUrl = "";
    const fetcher: typeof fetch = async (input) => {
      upstreamUrl = String(input);
      return new Response(null, { status: 200 });
    };
    const request = new Request(
      "http://console.test/api/agui/threads/thread%2F1/runs/run%2F1/cancel",
      { method: "POST", headers: { Cookie: "harness_access_token=user-jwt" } },
    );

    await proxyAguiRequest(
      request,
      config,
      fetcher,
      "threads/thread%2F1/runs/run%2F1/cancel",
    );

    expect(upstreamUrl).toBe(
      "http://harness.internal:8000/v1/agui/threads/thread%2F1/runs/run%2F1/cancel",
    );
  });

  it("forwards multipart bytes without exposing internal identity in the response", async () => {
    let upstreamInit: RequestInit | undefined;
    const fetcher: typeof fetch = async (_input, init) => {
      upstreamInit = init;
      return Response.json(
        { input_artifact_id: "input_artifact_1" },
        { status: 201 },
      );
    };
    const request = new Request("http://console.test/api/input-artifacts", {
      method: "POST",
      headers: {
        "Content-Type": "multipart/form-data; boundary=test",
        Cookie: "harness_access_token=user-jwt",
      },
      body: "--test--",
    });

    const response = await proxyInputArtifactRequest(request, config, fetcher);

    const headers = new Headers(upstreamInit?.headers);
    expect(headers.get("Content-Type")).toContain("boundary=test");
    expect(headers.get("X-Tenant-ID")).toBeNull();
    expect(headers.get("Authorization")).toBe("Bearer user-jwt");
    expect(await response.json()).toEqual({
      input_artifact_id: "input_artifact_1",
    });
    expect(response.headers.get("X-Tenant-ID")).toBeNull();
  });

  it("returns a generic 502 when the internal Harness endpoint is unavailable", async () => {
    const fetcher: typeof fetch = async () => {
      throw new Error("connect ECONNREFUSED http://harness.internal:8000");
    };

    const response = await proxyAguiRequest(
      new Request("http://console.test/api/agui", {
        method: "POST",
        body: "{}",
      }),
      config,
      fetcher,
    );

    expect(response.status).toBe(502);
    expect(await response.text()).not.toContain("harness.internal");
  });

  it("proxies Studio mutations and bundle headers through the authenticated BFF", async () => {
    let upstreamUrl = "";
    let upstreamInit: RequestInit | undefined;
    const fetcher: typeof fetch = async (input, init) => {
      upstreamUrl = String(input);
      upstreamInit = init;
      return new Response("bundle", {
        status: 200,
        headers: {
          "Content-Type": "application/zip",
          "Content-Disposition": 'attachment; filename="agent-0.1.0.zip"',
          ETag: '"archive-hash"',
          "X-Agent-Package-SHA256": "package-hash",
        },
      });
    };
    const request = new Request(
      "http://console.test/api/studio/drafts/draft-1/bundle?download=true",
      { headers: { Cookie: "harness_access_token=user-jwt" } },
    );

    const response = await proxyStudioRequest(
      request,
      config,
      fetcher,
      "drafts/draft-1/bundle",
    );

    expect(upstreamUrl).toBe(
      "http://harness.internal:8000/v1/studio/drafts/draft-1/bundle?download=true",
    );
    const headers = new Headers(upstreamInit?.headers);
    expect(headers.get("Authorization")).toBe("Bearer user-jwt");
    expect(headers.get("X-Harness-Service-Token")).toBe("server-only-token");
    expect(response.headers.get("Content-Disposition")).toContain("agent-0.1.0.zip");
    expect(response.headers.get("ETag")).toBe('"archive-hash"');
    expect(response.headers.get("X-Agent-Package-SHA256")).toBe("package-hash");
  });

  it("preserves lifecycle export filenames through the authenticated BFF", async () => {
    let upstreamUrl = "";
    const response = await proxyDataLifecycleRequest(
      new Request("http://console.test/api/data-lifecycle/jobs/job-1/artifact", {
        headers: { Cookie: "harness_access_token=user-jwt" },
      }),
      config,
      async (input) => {
        upstreamUrl = String(input);
        return new Response("zip", {
          headers: {
            "Content-Type": "application/zip",
            "Content-Disposition": "attachment; filename*=UTF-8''data-export.zip",
          },
        });
      },
      "jobs/job-1/artifact",
    );
    expect(upstreamUrl).toBe(
      "http://harness.internal:8000/v1/data-lifecycle/jobs/job-1/artifact",
    );
    expect(response.headers.get("Content-Disposition")).toContain("data-export.zip");
  });
});
