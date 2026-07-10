import { describe, expect, it } from "vitest";
import { approvalLabel } from "../src/components/approval-card";
import { parseSseBlock } from "../src/lib/agui";

describe("validation console contracts", () => {
  it("parses reconnectable AG-UI SSE", () => {
    expect(parseSseBlock('id: 2\ndata: {"type":"RUN_STARTED"}')).toEqual({
      id: "2",
      event: { type: "RUN_STARTED" },
    });
  });

  it("renders an explicit pending approval label", () => {
    expect(approvalLabel("pending")).toBe("等待人工审批");
  });
});

