import { describe, expect, it } from "vitest";
import type { RunAgentInput } from "@ag-ui/client";
import { HarnessHttpAgent } from "../src/lib/harness-agent";

describe("HarnessHttpAgent", () => {
  it("notifies Harness when CopilotRuntime stops an active thread", () => {
    let cancelUrl = "";
    let cancelInit: RequestInit | undefined;
    const cancelFetch: typeof fetch = async (input, init) => {
      cancelUrl = String(input);
      cancelInit = init;
      return new Response(null, { status: 202 });
    };
    const agent = new HarnessHttpAgent({
      url: "http://harness/v1/agui?agent_name=echo-agent&agent_version=0.1.0",
      headers: { "X-Tenant-ID": "local", "X-User-ID": "developer" },
      cancelFetch,
    });
    const input: RunAgentInput = {
      threadId: "thread/1",
      runId: "run/1",
      state: {},
      messages: [],
      tools: [],
      context: [],
      forwardedProps: {},
    };

    agent.run(input);
    agent.abortRun();

    expect(cancelUrl).toBe(
      "http://harness/v1/agui/threads/thread%2F1/runs/run%2F1/cancel",
    );
    expect(cancelInit).toEqual({
      method: "POST",
      headers: { "X-Tenant-ID": "local", "X-User-ID": "developer" },
    });
  });
});
