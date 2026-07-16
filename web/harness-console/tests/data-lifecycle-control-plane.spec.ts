import { readFileSync } from "node:fs";
import { join } from "node:path";
import { afterEach, describe, expect, it, vi } from "vitest";
import { lifecycleClient } from "../src/lib/studio-client";

const page = readFileSync(join(process.cwd(), "src/app/studio/data/page.tsx"), "utf8");
const component = readFileSync(join(process.cwd(), "src/components/agent-studio/data-lifecycle-control-plane.tsx"), "utf8");
const styles = readFileSync(join(process.cwd(), "src/components/agent-studio/data-lifecycle-control-plane.module.css"), "utf8");

describe("Data lifecycle control plane", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("shows retention, legal holds, adapter progress and self service", () => {
    expect(page).toContain("DataLifecycleControlPlane");
    expect(component).toContain("保留周期");
    expect(component).toContain("Legal Hold");
    expect(component).toContain("导出我的数据");
    expect(component).toContain("删除我的数据");
    expect(component).toContain("重试失败步骤");
    expect(component).toContain("/artifact");
    expect(styles).toContain(".cascade");
    expect(styles).not.toContain("linear-gradient");
    expect(styles).toContain("@media(max-width:620px)");
  });

  it("sends revision-protected policy and idempotent job requests", async () => {
    const calls: Array<{ url: string; body: unknown }> = [];
    vi.stubGlobal("fetch", async (input: RequestInfo | URL, init?: RequestInit) => {
      calls.push({
        url: String(input),
        body: init?.body ? JSON.parse(String(init.body)) : null,
      });
      return Response.json({});
    });
    const policy = {
      tenantId: "tenant-a", policyId: "tenant-default", revision: 3,
      sessionDays: 90, artifactDays: 90, traceDays: 30, evalDays: 365,
      updatedBy: "admin", updatedAt: "2026-07-16T00:00:00Z",
    };
    await lifecycleClient.replacePolicy(policy, policy);
    await lifecycleClient.createJob(
      "export", { kind: "user", subjectId: "user-1" }, "export:key-1",
    );
    expect(calls).toEqual([
      {
        url: "/api/data-lifecycle/retention-policy",
        body: {
          expectedRevision: 3,
          sessionDays: 90,
          artifactDays: 90,
          traceDays: 30,
          evalDays: 365,
        },
      },
      {
        url: "/api/data-lifecycle/jobs",
        body: {
          kind: "export",
          scope: { kind: "user", subjectId: "user-1" },
          idempotencyKey: "export:key-1",
        },
      },
    ]);
  });
});
