import { describe, expect, it } from "vitest";
import type { RunAgentInput } from "@ag-ui/client";
import { HarnessHttpAgent } from "../src/lib/harness-agent";
import { runStreamStore } from "../src/lib/run-stream-store";

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

  it("notifies Harness when assistant-ui aborts its run signal", async () => {
    let cancelUrl = "";
    const cancelFetch: typeof fetch = async (input) => {
      cancelUrl = String(input);
      return new Response(null, { status: 202 });
    };
    const streamFetch: typeof fetch = async () =>
      new Response(
        [
          'data: {"type":"RUN_STARTED","threadId":"thread-1","runId":"run-1"}',
          "",
          'data: {"type":"RUN_FINISHED","threadId":"thread-1","runId":"run-1"}',
          "",
          "",
        ].join("\n"),
        { headers: { "Content-Type": "text/event-stream" } },
      );
    const agent = new HarnessHttpAgent({
      url: "http://harness/v1/agui?agent_name=echo-agent&agent_version=0.1.0",
      cancelFetch,
      fetch: streamFetch,
    });
    const input: RunAgentInput = {
      threadId: "thread-1",
      runId: "run-1",
      state: {},
      messages: [],
      tools: [],
      context: [],
      forwardedProps: {},
    };
    const abortController = new AbortController();

    const run = (
      agent.runAgent as unknown as (
        parameters: RunAgentInput,
        subscriber: undefined,
        options: { signal: AbortSignal },
      ) => Promise<unknown>
    )(input, undefined, { signal: abortController.signal });
    abortController.abort();
    await run;

    expect(cancelUrl).toBe(
      "http://harness/v1/agui/threads/thread-1/runs/run-1/cancel",
    );
  });

  it("binds the browser fetch receiver for cancellation", () => {
    const originalFetch = globalThis.fetch;
    let receiver: unknown;
    globalThis.fetch = function (this: unknown) {
      receiver = this;
      return Promise.resolve(new Response(null, { status: 202 }));
    } as typeof fetch;
    try {
      const agent = new HarnessHttpAgent({ url: "http://harness/v1/agui" });
      const input: RunAgentInput = {
        threadId: "thread-1",
        runId: "run-1",
        state: {},
        messages: [],
        tools: [],
        context: [],
        forwardedProps: {},
      };

      agent.run(input);
      agent.abortRun();

      expect(receiver).toBe(globalThis);
    } finally {
      globalThis.fetch = originalFetch;
    }
  });

  it("forwards native text deltas while tracking run lifecycle without duplicating text", async () => {
    const lifecycle: string[] = [];
    const deltas: string[] = [];
    runStreamStore.clear();
    const unsubscribe = runStreamStore.subscribe(() => {
      lifecycle.push(runStreamStore.getSnapshot().status);
    });
    const streamFetch: typeof fetch = async () =>
      new Response(
        [
          'data: {"type":"RUN_STARTED","threadId":"thread-stream","runId":"run-stream"}',
          "",
          'data: {"type":"TEXT_MESSAGE_START","messageId":"message-stream","role":"assistant"}',
          "",
          'data: {"type":"TEXT_MESSAGE_CONTENT","messageId":"message-stream","delta":"第一段"}',
          "",
          'data: {"type":"TEXT_MESSAGE_CONTENT","messageId":"message-stream","delta":"第二段"}',
          "",
          'data: {"type":"TEXT_MESSAGE_END","messageId":"message-stream"}',
          "",
          'data: {"type":"RUN_FINISHED","threadId":"thread-stream","runId":"run-stream"}',
          "",
          "",
        ].join("\n"),
        { headers: { "Content-Type": "text/event-stream" } },
      );
    const agent = new HarnessHttpAgent({
      url: "http://harness/v1/agui",
      fetch: streamFetch,
    });

    await agent.runAgent(
      { runId: "run-stream" },
      {
        onTextMessageContentEvent: ({ event }) => {
          deltas.push(event.delta);
        },
      },
    );

    expect(deltas).toEqual(["第一段", "第二段"]);
    expect(lifecycle).toEqual(["running", "complete"]);
    expect(runStreamStore.getSnapshot()).toMatchObject({
      runId: "run-stream",
      status: "complete",
    });
    unsubscribe();
  });
});
