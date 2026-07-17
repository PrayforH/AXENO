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

  it("links directly to a validated trace when its id is available", () => {
    const url = buildLangfuseTraceListUrl(
      {
        LANGFUSE_BASE_URL: "http://langfuse.internal:3000/",
        LANGFUSE_PROJECT_ID: "project-1",
      },
      "run_123",
      "CB10528AFF900CA9A1A8813C4947582E",
    );

    expect(url?.toString()).toBe(
      "http://langfuse.internal:3000/project/project-1/traces/cb10528aff900ca9a1a8813c4947582e",
    );
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

  it("falls back to run search for an invalid trace id", () => {
    const url = buildLangfuseTraceListUrl(
      {
        LANGFUSE_BASE_URL: "https://langfuse.test",
        LANGFUSE_PROJECT_ID: "project-1",
      },
      "run_123",
      "../admin",
    );

    expect(url?.toString()).toBe(
      "https://langfuse.test/project/project-1/traces?search=run_123",
    );
  });
});
