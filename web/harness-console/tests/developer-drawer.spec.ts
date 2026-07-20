import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { developerRows } from "../src/lib/developer-details";
import { notableActivityItems } from "../src/components/developer-drawer";
import type { ActivityItem } from "../src/lib/activity-schema";

const panel = readFileSync(
  join(process.cwd(), "src/components/developer-drawer.tsx"),
  "utf8",
);
const styles = readFileSync(join(process.cwd(), "src/app/styles.css"), "utf8");
const codexTheme = readFileSync(
  join(process.cwd(), "src/app/codex-theme.css"),
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

  it("keeps the local panel concise and delegates deep diagnosis to Langfuse", () => {
    expect(panel).toContain("运行详情");
    expect(panel).toContain("本次运行");
    expect(panel).toContain("打开 Trace");
    expect(panel).toContain("Trace 尚未生成");
    expect(panel).toContain("还没有运行记录");
    expect(panel).not.toContain("inspector-title-mark");
    expect(panel).not.toContain("observability-mark");
    expect(panel).not.toContain("empty-orbit");
    expect(panel).not.toContain("高级诊断");
    expect(panel).not.toContain("Harness activity");
    expect(panel).not.toContain("Run inspector");
    expect(panel).not.toContain("协议与原始事件");
  });

  it("uses a compact metric grid and quiet observability row", () => {
    expect(panel).toContain('className="run-metric-wide"');
    expect(codexTheme).toMatch(
      /body\.codex-theme-v1 \.developer-drawer \.run-metrics\s*\{[^}]*grid-template-columns:\s*repeat\(2,\s*minmax\(0,\s*1fr\)\);/s,
    );
    expect(codexTheme).toMatch(
      /body\.codex-theme-v1 \.observability-link\s*\{[^}]*min-height:\s*52px;/s,
    );
    expect(codexTheme).toMatch(
      /body\.codex-theme-v1 \.developer-drawer \.run-counts span\s*\{[^}]*background:\s*transparent;/s,
    );
  });

  it("keeps identifiers collapsed and links the current run to observability", () => {
    const identifiersStart = panel.indexOf('<details className="run-identifiers">');

    expect(identifiersStart).toBeGreaterThan(-1);
    expect(panel).toContain("/api/harness/observability?run_id=");
    expect(panel).toContain("&trace_id=");
    expect(panel).toContain("activity.trace_id");
    expect(panel.slice(identifiersStart)).toContain("activity.run_id");
    expect(panel.slice(identifiersStart)).toContain("threadId");
    expect(panel).not.toContain("developerRows(threadId)");
  });

  it("removes streaming noise from the collapsed local activity list", () => {
    const item = (eventType: string, kind = "run", status = "succeeded", sequence = 1) => ({
      id: `${eventType}-${sequence}`,
      event_type: eventType,
      kind,
      status,
      title: eventType,
      summary: null,
      timestamp: "2026-07-16T00:00:00Z",
      sequence,
      metadata: {},
    }) as ActivityItem;

    const visible = notableActivityItems([
      item("message.delta", "analysis", "running", 1),
      item("tool.request", "tool", "running", 2),
      item("tool.result", "tool", "failed", 3),
      item("subagent.completed", "subagent", "completed", 4),
      item("run.succeeded", "result", "succeeded", 5),
    ]);

    expect(visible.map((entry) => entry.event_type)).toEqual([
      "tool.result",
      "subagent.completed",
      "run.succeeded",
    ]);
  });

  it("uses a desktop side panel and a mobile bottom sheet", () => {
    expect(styles).toContain("grid-template-columns: minmax(0, 1fr) 340px");
    expect(styles).toMatch(/@media \(max-width: 980px\)[\s\S]*\.workspace-stage\.inspector-open \.developer-drawer[\s\S]*max-height: min\(78dvh, 760px\)/);
    expect(styles).toMatch(/\.workspace-stage\.inspector-open \.developer-drawer[\s\S]*inset: auto 0 0/);
  });

  it("uses semantic pulse colors for waiting and terminal states", () => {
    expect(styles).toMatch(
      /\.activity-pulse\.status-waiting\s*\{[^}]*background:\s*var\(--signal\);/s,
    );
    expect(styles).toMatch(
      /\.activity-pulse\.status-failed,[\s\S]*?\.activity-pulse\.status-timed_out\s*\{[^}]*background:\s*#a94442;/s,
    );
  });

  it("gives the narrow bottom sheet modal focus behavior", () => {
    expect(panel).toContain('window.matchMedia("(max-width: 980px)")');
    expect(panel).toContain('role={isModal ? "dialog" : undefined}');
    expect(panel).toContain("aria-modal={isModal || undefined}");
    expect(panel).toContain('event.key === "Escape"');
    expect(panel).toContain("background.inert = true");
    expect(panel).toContain("closeButtonRef.current?.focus()");
    expect(panel).toContain("previouslyFocused?.focus()");
    expect(panel).toContain("isHiddenByCollapsedDetails(element)");
    expect(panel).toContain("element.getClientRects().length > 0");
  });
});
