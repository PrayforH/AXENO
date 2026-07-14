import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { developerRows } from "../src/lib/developer-details";

const panel = readFileSync(
  join(process.cwd(), "src/components/developer-drawer.tsx"),
  "utf8",
);

describe("developer drawer", () => {
  it("shows protocol coordinates without leaking server identity", () => {
    const rows = developerRows("thread-1");

    expect(rows).toEqual([
      ["THREAD", "thread-1"],
      ["AGENT", "harness-agent"],
      ["ROUTE", "/api/agui → Harness AG-UI"],
    ]);
    expect(JSON.stringify(rows)).not.toContain("X-Tenant-ID");
    expect(JSON.stringify(rows)).not.toContain("developer");
  });

  it("keeps technical data behind user-facing run details", () => {
    expect(panel).toContain("Current run");
    expect(panel).toContain("本次运行");
    expect(panel).toContain("还没有运行记录");
    expect(panel).toContain("高级诊断");
    expect(panel).not.toContain("Run inspector");
    expect(panel).not.toContain("协议与原始事件");
  });
});
