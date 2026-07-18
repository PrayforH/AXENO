import { beforeEach, describe, expect, it } from "vitest";
import { liveResponseStore } from "../src/lib/live-response-store";

describe("liveResponseStore", () => {
  beforeEach(() => liveResponseStore.clear());

  it("keeps one direct stream while moving tool commentary out of the answer", () => {
    liveResponseStore.startRun("run-1");
    liveResponseStore.startMessage("commentary");
    liveResponseStore.append("commentary", "先检索资料");

    expect(liveResponseStore.getSnapshot()).toMatchObject({
      text: "先检索资料",
      status: "streaming",
      visible: true,
    });

    liveResponseStore.hideForTool();
    expect(liveResponseStore.getSnapshot()).toMatchObject({
      text: "先检索资料",
      visible: false,
    });

    liveResponseStore.startMessage("final");
    liveResponseStore.append("final", "最终");
    liveResponseStore.append("final", "回答");
    liveResponseStore.completeMessage("final");

    expect(liveResponseStore.getSnapshot()).toMatchObject({
      runId: "run-1",
      messageId: "final",
      text: "最终回答",
      status: "complete",
      visible: true,
    });
  });
});
