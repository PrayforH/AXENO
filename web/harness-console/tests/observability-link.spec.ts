import { describe, expect, it } from "vitest";
import { buildLangfuseTraceListUrl } from "../src/lib/observability-link";

describe("Langfuse observability link", () => {
  it("builds a project trace search without exposing credentials", () => {
    const url = buildLangfuseTraceListUrl(
      {
        LANGFUSE_BASE_URL: "http://langfuse.internal:3000/",
        LANGFUSE_PROJECT_ID: "project-1",
      },
      "run_123",
    );

    expect(url?.toString()).toBe(
      "http://langfuse.internal:3000/project/project-1/traces?search=run_123",
    );
    expect(url?.toString()).not.toContain("sk-lf");
  });

  it("rejects incomplete or unsafe configuration", () => {
    expect(buildLangfuseTraceListUrl({}, "run_123")).toBeUndefined();
    expect(
      buildLangfuseTraceListUrl(
        { LANGFUSE_BASE_URL: "javascript:alert(1)", LANGFUSE_PROJECT_ID: "project-1" },
        "run_123",
      ),
    ).toBeUndefined();
    expect(
      buildLangfuseTraceListUrl(
        { LANGFUSE_BASE_URL: "https://langfuse.test", LANGFUSE_PROJECT_ID: "../admin" },
        "run_123",
      ),
    ).toBeUndefined();
  });
});
