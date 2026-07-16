import { streamAgui, type AguiEvent } from "./agui";

export type Identity = { tenantId: string; userId: string };
export type Run = { run_id: string; session_id: string; status: string };
export type Artifact = { artifact_id: string; name: string; media_type: string; size_bytes?: number };

export class HarnessClient {
  constructor(
    private readonly baseUrl: string,
    private readonly identity: Identity,
  ) {}

  private headers(extra: Record<string, string> = {}) {
    return {
      "Content-Type": "application/json",
      "X-Tenant-ID": this.identity.tenantId,
      "X-User-ID": this.identity.userId,
      ...extra,
    };
  }

  private async json<T>(path: string, init: RequestInit = {}): Promise<T> {
    const response = await fetch(`${this.baseUrl}${path}`, {
      ...init,
      headers: { ...this.headers(), ...(init.headers ?? {}) },
    });
    if (!response.ok) throw new Error((await response.text()) || `HTTP ${response.status}`);
    return response.json() as Promise<T>;
  }

  publishAgent(path: string) {
    return this.json<{ name: string; version: string }>("/v1/agents", {
      method: "POST",
      body: JSON.stringify({ path }),
    });
  }

  createSession(agentName: string, agentVersion: string) {
    return this.json<{ session_id: string }>("/v1/sessions", {
      method: "POST",
      body: JSON.stringify({ agent_name: agentName, agent_version: agentVersion }),
    });
  }

  createRun(sessionId: string, prompt: string) {
    return this.json<Run>(`/v1/sessions/${sessionId}/runs`, {
      method: "POST",
      headers: { "Idempotency-Key": crypto.randomUUID() },
      body: JSON.stringify({ prompt }),
    });
  }

  getRun(runId: string) { return this.json<Run>(`/v1/runs/${runId}`); }
  cancel(runId: string) { return this.json<Run>(`/v1/runs/${runId}/cancel`, { method: "POST" }); }
  approve(approvalId: string, decision: "approved" | "rejected") {
    return this.json(`/v1/approvals/${approvalId}`, {
      method: "PUT",
      body: JSON.stringify({ decision }),
    });
  }
  artifacts(runId: string) { return this.json<Artifact[]>(`/v1/runs/${runId}/artifacts`); }
  async downloadArtifact(artifact: Artifact) {
    const response = await fetch(`${this.baseUrl}/v1/artifacts/${artifact.artifact_id}/content`, {
      headers: this.headers(),
    });
    if (!response.ok) throw new Error(`Artifact download failed: ${response.status}`);
    const url = URL.createObjectURL(await response.blob());
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = artifact.name;
    anchor.click();
    URL.revokeObjectURL(url);
  }

  async events(runId: string, lastEventId: string | undefined, onEvent: (id: string | undefined, event: AguiEvent) => void) {
    const response = await fetch(`${this.baseUrl}/v1/agui/runs/${runId}/events`, {
      headers: this.headers(lastEventId ? { "Last-Event-ID": lastEventId } : {}),
    });
    await streamAgui(response, onEvent);
  }
}
