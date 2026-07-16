import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

const page = readFileSync(join(process.cwd(), "src/app/studio/usage/page.tsx"), "utf8");
const component = readFileSync(join(process.cwd(), "src/components/agent-studio/quota-control-plane.tsx"), "utf8");
const styles = readFileSync(join(process.cwd(), "src/components/agent-studio/quota-control-plane.module.css"), "utf8");

describe("Studio quota control plane", () => {
  it("renders real quota counters and a revision-protected editor", () => {
    expect(page).toContain("QuotaControlPlane");
    expect(component).toContain("studioClient.quotaUsage");
    expect(component).toContain("studioClient.replaceQuotaPolicy");
    expect(component).toContain("globalPolicy.revision");
    expect(component).toContain("usage.unknownCostEntries");
    expect(component).toContain("usage.activeReservations");
    expect(component).toContain('membership.role === "owner" || membership.role === "admin"');
  });

  it("uses one capacity-ledger visual language and stays responsive", () => {
    expect(component).toContain('aria-label="租户配额使用量"');
    expect(component).toContain('role="progressbar"');
    expect(component).toContain('min={1} step={1}');
    expect(styles).toContain(".ledger");
    expect(styles).toContain(".track");
    expect(styles).not.toContain("linear-gradient");
    expect(styles).toContain("@media (max-width: 620px)");
  });
});
