import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

const files = readFileSync(
  join(process.cwd(), "src/components/my-files/my-files.tsx"),
  "utf8",
);
const account = readFileSync(
  join(process.cwd(), "src/components/account-menu.tsx"),
  "utf8",
);
const route = readFileSync(
  join(process.cwd(), "src/app/api/harness/artifacts/route.ts"),
  "utf8",
);

describe("my files", () => {
  it("indexes generated deliverables with search, type filters and task provenance", () => {
    expect(files).toContain("我的文件");
    expect(files).toContain('fetch("/api/harness/artifacts?limit=500"');
    expect(files).toContain("搜索文件名、任务或智能体");
    expect(files).toContain("task_archived");
    expect(files).toContain("打开任务");
    expect(files).toContain("download");
  });

  it("keeps the entry under the account control and proxies downloads through authenticated routes", () => {
    expect(account).toContain('href: "/studio/files"');
    expect(account).toContain('label: "我的文件"');
    expect(route).toContain("listArtifacts(request)");
    expect(files).toContain("/api/harness/artifacts/${encodeURIComponent(file.artifact_id)}");
  });
});
