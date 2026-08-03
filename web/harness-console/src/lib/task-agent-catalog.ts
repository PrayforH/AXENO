import { requireAuthenticatedResponse } from "./client-auth";
import type { StudioDraftSummary } from "./studio-client";

export interface TaskAgent {
  name: string;
  version: string;
  displayName: string;
  domain: string;
  modelRoute?: string;
  model?: string;
  modelCapabilities?: string[];
  ownerUserId?: string;
  scope?: "personal" | "team";
  spaceId?: string;
  spaceName?: string;
  runnableByViewer?: boolean;
}

interface RuntimeAgent {
  name: string;
  version: string;
}

interface PublishedAgent {
  name: string;
  version: string;
  display_name: string;
  domain: string;
  model_route?: string | null;
  model?: string | null;
  model_capabilities?: string[];
  owner_user_id: string;
  scope: "personal" | "team";
  space_id?: string | null;
  space_name?: string | null;
  runnable_by_viewer?: boolean;
}

export interface TaskAgentCatalog {
  agents: TaskAgent[];
  defaultAgent: TaskAgent;
}

async function json<T>(url: string): Promise<T> {
  const response = requireAuthenticatedResponse(
    await fetch(url, { cache: "no-store" }),
  );
  if (!response.ok) {
    throw new Error((await response.text()) || `HTTP ${response.status}`);
  }
  return response.json() as Promise<T>;
}

export async function loadTaskAgentCatalog(): Promise<TaskAgentCatalog> {
  const runtime = await json<RuntimeAgent>("/api/harness/runtime-config");
  let registry: PublishedAgent[] = [];
  try {
    registry = await json<PublishedAgent[]>("/api/harness/agents");
  } catch {
    // Keep the configured runtime and Studio versions usable during API upgrades.
  }
  let drafts: StudioDraftSummary[] = [];
  try {
    drafts = await json<StudioDraftSummary[]>("/api/studio/drafts");
  } catch {
    // Running tasks must remain usable when Studio is temporarily unavailable.
  }
  const studioVersions = drafts
    .filter(
      (draft): draft is StudioDraftSummary & { publishedVersion: string } =>
        Boolean(draft.publishedVersion),
    )
    .map((draft) => ({
      name: draft.name,
      version: draft.publishedVersion,
      displayName: draft.displayName,
      domain: draft.domain,
    }));
  const studioByCoordinate = new Map(
    studioVersions.map((agent) => [`${agent.name}@${agent.version}`, agent]),
  );
  const registryVersions = registry.map((agent) => {
    const studio = studioByCoordinate.get(`${agent.name}@${agent.version}`);
    const sharing = {
      ownerUserId: agent.owner_user_id,
      scope: agent.scope,
      spaceId: agent.space_id ?? undefined,
      spaceName: agent.space_name ?? undefined,
      runnableByViewer: agent.runnable_by_viewer ?? true,
    } as const;
    return (
      studio
        ? {
            ...studio,
            ...sharing,
            modelRoute: agent.model_route ?? undefined,
            model: agent.model ?? undefined,
            modelCapabilities: agent.model_capabilities ?? [],
          }
        : {
        name: agent.name,
        version: agent.version,
        displayName:
          agent.display_name === "public-opinion-agent"
            ? "舆情分析"
            : agent.display_name,
        domain: agent.domain,
        ...sharing,
        modelRoute: agent.model_route ?? undefined,
        model: agent.model ?? undefined,
        modelCapabilities: agent.model_capabilities ?? [],
      }
    );
  });
  const published = [...registryVersions, ...studioVersions].filter(
    (agent, index, values) =>
      values.findIndex(
        (candidate) => agentCoordinate(candidate) === agentCoordinate(agent),
      ) === index,
  );
  const runtimeMatch = published.find(
    (agent) => agent.name === runtime.name && agent.version === runtime.version,
  );
  const defaultAgent = runtimeMatch ?? {
    name: runtime.name,
    version: runtime.version,
    displayName: runtime.name,
    domain: "default",
  };
  const agents = runtimeMatch
    ? published
    : [defaultAgent, ...published];
  return {
    defaultAgent,
    agents: agents.filter(
      (agent, index, values) =>
        values.findIndex(
          (candidate) =>
            candidate.name === agent.name && candidate.version === agent.version,
        ) === index,
    ),
  };
}

export function agentCoordinate(agent: Pick<TaskAgent, "name" | "version">) {
  const scoped = agent as Pick<
    TaskAgent,
    "name" | "version" | "ownerUserId" | "spaceId" | "scope"
  >;
  if (!scoped.scope && !scoped.spaceId && !scoped.ownerUserId) {
    return `${agent.name}@${agent.version}`;
  }
  return `${scoped.scope ?? "personal"}:${scoped.spaceId ?? "-"}:${scoped.ownerUserId ?? "-"}:${agent.name}@${agent.version}`;
}
