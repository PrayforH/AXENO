import {
  type AgentSubscriber,
  HttpAgent,
  type HttpAgentConfig,
  type RunAgentParameters,
  type RunAgentInput,
  type RunAgentResult,
} from "@ag-ui/client";
import { runActivitySchema } from "./activity-schema";
import {
  type ActivityPatchOperation,
  activityStore,
} from "./activity-store";
import { runStreamStore } from "./run-stream-store";
import { redirectOnUnauthorized } from "./client-auth";

export interface HarnessHttpAgentConfig extends HttpAgentConfig {
  cancelFetch?: typeof fetch;
}

interface AssistantUiRunOptions {
  signal?: AbortSignal;
}

export class HarnessHttpAgent extends HttpAgent {
  private activeInput?: Pick<RunAgentInput, "threadId" | "runId">;
  private cancelFetch: typeof fetch;

  constructor(config: HarnessHttpAgentConfig) {
    const transportFetch = config.fetch ?? globalThis.fetch.bind(globalThis);
    const sessionAwareFetch: typeof transportFetch = async (url, init) => {
      const response = await transportFetch(url, init);
      redirectOnUnauthorized(response);
      return response;
    };
    super({ ...config, fetch: sessionAwareFetch });
    const cancelTransport = config.cancelFetch ?? globalThis.fetch.bind(globalThis);
    this.cancelFetch = async (input, init) => {
      const response = await cancelTransport(input, init);
      redirectOnUnauthorized(response);
      return response;
    };
  }

  override run(input: RunAgentInput) {
    this.activeInput = { threadId: input.threadId, runId: input.runId };
    return super.run(input);
  }

  override runAgent(
    parameters?: RunAgentParameters,
    subscriber?: AgentSubscriber,
    options?: AssistantUiRunOptions,
  ): Promise<RunAgentResult> {
    const input = parameters as Partial<RunAgentInput> | undefined;
    let activeInput: Pick<RunAgentInput, "threadId" | "runId"> | undefined;
    if (input?.runId) {
      activeInput = {
        threadId: input.threadId || this.threadId || "main",
        runId: input.runId,
      };
      this.activeInput = activeInput;
    }
    const wrapped: AgentSubscriber = {
      ...subscriber,
      onRunStartedEvent: async (params) => {
        runStreamStore.startRun(params.event.runId);
        return subscriber?.onRunStartedEvent?.(params);
      },
      onRunFinishedEvent: async (params) => {
        runStreamStore.completeRun(params.event.runId);
        return subscriber?.onRunFinishedEvent?.(params);
      },
      onRunErrorEvent: async (params) => {
        runStreamStore.failRun(
          typeof params.event.runId === "string"
            ? params.event.runId
            : undefined,
        );
        return subscriber?.onRunErrorEvent?.(params);
      },
      onActivitySnapshotEvent: async (params) => {
        if (params.event.activityType === "harness.run.v1") {
          const parsed = runActivitySchema.safeParse(params.event.content);
          if (parsed.success) activityStore.publish(parsed.data);
        }
        return subscriber?.onActivitySnapshotEvent?.(params);
      },
      onActivityDeltaEvent: async (params) => {
        if (params.event.activityType === "harness.run.v1") {
          activityStore.patch(
            params.event.patch as readonly ActivityPatchOperation[],
          );
        }
        return subscriber?.onActivityDeltaEvent?.(params);
      },
    };
    const signal = options?.signal;
    const cancelFromSignal = () => this.cancelActiveRun();
    if (signal?.aborted) cancelFromSignal();
    else signal?.addEventListener("abort", cancelFromSignal, { once: true });

    return super.runAgent(parameters, wrapped).finally(() => {
      signal?.removeEventListener("abort", cancelFromSignal);
      if (
        activeInput &&
        this.activeInput?.threadId === activeInput.threadId &&
        this.activeInput.runId === activeInput.runId
      ) {
        this.activeInput = undefined;
      }
    });
  }

  cancelActiveRun(): void {
    if (!this.activeInput) return;
    const relative = this.url.startsWith("/");
    const base = globalThis.location?.origin ?? "http://localhost";
    const url = new URL(this.url, base);
    url.search = "";
    url.pathname = `${url.pathname.replace(/\/$/, "")}/threads/${encodeURIComponent(
      this.activeInput.threadId,
    )}/runs/${encodeURIComponent(this.activeInput.runId)}/cancel`;
    const target = relative ? `${url.pathname}${url.search}` : url.toString();
    void this.cancelFetch(target, {
      method: "POST",
      headers: this.headers,
    }).catch((error: unknown) => {
      console.error("[Harness Console] Failed to cancel Harness run", error);
    });
    this.activeInput = undefined;
  }

  override abortRun(): void {
    this.cancelActiveRun();
    super.abortRun();
  }

  override clone(): HarnessHttpAgent {
    const cloned = super.clone() as HarnessHttpAgent;
    cloned.cancelFetch = this.cancelFetch;
    cloned.activeInput = this.activeInput ? { ...this.activeInput } : undefined;
    return cloned;
  }
}
