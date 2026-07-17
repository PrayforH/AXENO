import { afterEach, describe, expect, it, vi } from "vitest";
import {
  agentCoordinate,
  loadTaskAgentCatalog,
} from "../src/lib/task-agent-catalog";

describe("task agent catalog", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("offers published Studio versions and keeps the configured runtime first-class", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
        if (url.includes("runtime-config")) {
          return Response.json({ name: "public-opinion-agent", version: "0.2.0" });
        }
        if (url.includes("/api/harness/agents")) {
          return Response.json([
            {
              name: "public-opinion-agent",
              version: "0.2.0",
              display_name: "public-opinion-agent",
              domain: "public-opinion",
            },
          ]);
        }
        return Response.json([
          {
            draftId: "draft-1",
            name: "public-opinion-agent",
            displayName: "舆情研判 Agent",
            domain: "public-opinion",
            version: "0.2.0",
            template: "orchestrator",
            revision: 4,
            updatedAt: "2026-07-17T00:00:00Z",
            publishedVersion: "0.2.0",
          },
          {
            draftId: "draft-2",
            name: "draft-only",
            displayName: "未发布 Agent",
            domain: "draft",
            version: "0.1.0",
            template: "analyst",
            revision: 1,
            updatedAt: "2026-07-17T00:00:00Z",
            publishedVersion: null,
          },
        ]);
      }),
    );

    const catalog = await loadTaskAgentCatalog();

    expect(catalog.defaultAgent.displayName).toBe("舆情研判 Agent");
    expect(catalog.agents).toHaveLength(1);
    expect(agentCoordinate(catalog.agents[0])).toBe(
      "public-opinion-agent@0.2.0",
    );
  });

  it("falls back to the configured runtime when Studio is unavailable", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) =>
        String(input).includes("runtime-config")
          ? Response.json({ name: "echo-agent", version: "0.4.0" })
          : new Response("offline", { status: 503 }),
      ),
    );

    const catalog = await loadTaskAgentCatalog();

    expect(catalog.agents).toEqual([
      {
        name: "echo-agent",
        version: "0.4.0",
        displayName: "echo-agent",
        domain: "default",
      },
    ]);
  });

  it("offers published runtime bundles even when they have no Studio draft", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
        if (url.includes("runtime-config")) {
          return Response.json({ name: "echo-agent", version: "0.4.0" });
        }
        if (url.includes("/api/harness/agents")) {
          return Response.json([
            {
              name: "echo-agent",
              version: "0.4.0",
              display_name: "echo-agent",
              domain: "harness-validation",
            },
            {
              name: "public-opinion-agent",
              version: "0.1.1",
              display_name: "public-opinion-agent",
              domain: "public-opinion",
            },
          ]);
        }
        return Response.json([]);
      }),
    );

    const catalog = await loadTaskAgentCatalog();

    expect(catalog.agents.map(agentCoordinate)).toEqual([
      "echo-agent@0.4.0",
      "public-opinion-agent@0.1.1",
    ]);
    expect(catalog.agents[1].displayName).toBe("舆情分析");
  });
});
