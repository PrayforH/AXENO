import {
  HttpAgent,
  type HttpAgentConfig,
  type RunAgentInput,
} from "@ag-ui/client";

export interface HarnessHttpAgentConfig extends HttpAgentConfig {
  cancelFetch?: typeof fetch;
}

export class HarnessHttpAgent extends HttpAgent {
  private activeInput?: Pick<RunAgentInput, "threadId" | "runId">;
  private cancelFetch: typeof fetch;

  constructor(config: HarnessHttpAgentConfig) {
    super(config);
    this.cancelFetch = config.cancelFetch ?? fetch;
  }

  override run(input: RunAgentInput) {
    this.activeInput = { threadId: input.threadId, runId: input.runId };
    return super.run(input);
  }

  override abortRun(): void {
    if (this.activeInput) {
      const url = new URL(this.url);
      url.search = "";
      url.pathname = `${url.pathname.replace(/\/$/, "")}/threads/${encodeURIComponent(
        this.activeInput.threadId,
      )}/runs/${encodeURIComponent(this.activeInput.runId)}/cancel`;
      void this.cancelFetch(url.toString(), {
        method: "POST",
        headers: this.headers,
      }).catch((error: unknown) => {
        console.error("[Harness Console] Failed to cancel Harness run", error);
      });
      this.activeInput = undefined;
    }
    super.abortRun();
  }

  override clone(): HarnessHttpAgent {
    const cloned = super.clone() as HarnessHttpAgent;
    cloned.cancelFetch = this.cancelFetch;
    cloned.activeInput = this.activeInput ? { ...this.activeInput } : undefined;
    return cloned;
  }
}
