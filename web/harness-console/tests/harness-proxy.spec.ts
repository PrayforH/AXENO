import { describe, expect, it } from "vitest";
import {
  proxyAguiRequest,
  proxyInputArtifactRequest,
} from "../src/lib/harness-proxy";
import type { HarnessServerConfig } from "../src/lib/server-config";

const config: HarnessServerConfig = {
  apiUrl: "http://harness.internal:8000",
  agentName: "echo-agent",
  agentVersion: "0.1.0",
  aguiUrl:
    "http://harness.internal:8000/v1/agui?agent_name=echo-agent&agent_version=0.1.0",
  identityHeaders: {
    "X-Tenant-ID": "local",
    "X-User-ID": "developer",
  },
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
      headers: { "Content-Type": "application/json", Cookie: "private=browser" },
      body: JSON.stringify({ threadId: "thread-1" }),
    });

    const response = await proxyAguiRequest(request, config, fetcher);

    expect(upstreamUrl).toBe(config.aguiUrl);
    const headers = new Headers(upstreamInit?.headers);
    expect(headers.get("X-Tenant-ID")).toBe("local");
    expect(headers.get("X-User-ID")).toBe("developer");
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
      { method: "POST" },
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
      headers: { "Content-Type": "multipart/form-data; boundary=test" },
      body: "--test--",
    });

    const response = await proxyInputArtifactRequest(request, config, fetcher);

    const headers = new Headers(upstreamInit?.headers);
    expect(headers.get("Content-Type")).toContain("boundary=test");
    expect(headers.get("X-Tenant-ID")).toBe("local");
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
});
