import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { developerRows } from "../src/lib/developer-details";

const panel = readFileSync(
  join(process.cwd(), "src/components/developer-drawer.tsx"),
  "utf8",
);
const styles = readFileSync(join(process.cwd(), "src/app/styles.css"), "utf8");

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

  it("keeps raw identifiers inside advanced diagnostics", () => {
    const advancedStart = panel.indexOf('<details className="raw-inspector">');

    expect(advancedStart).toBeGreaterThan(-1);
    expect(panel.slice(0, advancedStart)).not.toContain("activity.run_id");
    expect(panel.slice(advancedStart)).toContain("developerRows(threadId)");
    expect(panel.slice(advancedStart)).toContain("value={activity}");
  });

  it("uses a desktop side panel and a mobile bottom sheet", () => {
    const narrowStart = styles.indexOf("@media (max-width: 720px)");
    const narrowEnd = styles.indexOf("@media", narrowStart + 1);
    const narrowRules = styles.slice(narrowStart, narrowEnd);

    expect(styles).toContain("grid-template-columns: minmax(0, 1fr) 360px");
    expect(styles).toMatch(/@media \(max-width: 980px\)[\s\S]*\.workspace-stage\.inspector-open \.developer-drawer[\s\S]*max-height: 72dvh/);
    expect(styles).toMatch(/\.workspace-stage\.inspector-open \.developer-drawer[\s\S]*inset: auto 0 0/);
    expect(narrowRules).not.toContain(".developer-drawer");
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
