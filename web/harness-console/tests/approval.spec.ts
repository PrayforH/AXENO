import { describe, expect, it } from "vitest";
import * as approval from "../src/components/approval-card";
import { parseSseBlock } from "../src/lib/agui";

describe("validation console contracts", () => {
  it("parses reconnectable AG-UI SSE", () => {
    expect(parseSseBlock('id: 2\ndata: {"type":"RUN_STARTED"}')).toEqual({
      id: "2",
      event: { type: "RUN_STARTED" },
    });
  });

  it("renders an explicit pending approval label", () => {
    expect(approval.approvalLabel("pending")).toBe("等待人工审批");
  });

  it("uses a useful fallback when no policy reason is available", () => {
    expect(approval.formatApprovalReason(undefined)).toBe(
      "此操作需要你确认后才能继续。",
    );
  });

  it("formats safe approval context without authorization material", () => {
    expect("approvalContextRows" in approval).toBe(true);
    const contextRows = (
      approval as typeof approval & {
        approvalContextRows: (details: Record<string, unknown>) => Array<{
          label: string;
          value: string;
        }>;
      }
    ).approvalContextRows;

    const rows = contextRows({
      tool_name: "Bash",
      argument_summary: { command: "pwd", Authorization: "secret" },
      sandbox_provider: "daytona",
      sandbox_isolation: "container",
      policy_rule: "bash-review",
      risk: "high",
    });

    expect(rows).toEqual([
      { label: "工具", value: "Bash" },
      { label: "操作", value: "pwd" },
      { label: "环境", value: "daytona · container" },
      { label: "风险", value: "高" },
      { label: "策略", value: "bash-review" },
    ]);
    expect(JSON.stringify(rows)).not.toContain("secret");
  });
});
