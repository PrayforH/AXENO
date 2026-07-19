import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { liveResponseStore } from "../src/lib/live-response-store";

describe("liveResponseStore", () => {
  beforeEach(() => liveResponseStore.clear());
  afterEach(() => vi.unstubAllGlobals());

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

  it("coalesces browser deltas into one paint without delaying completion", () => {
    let paint: FrameRequestCallback | undefined;
    const requestFrame = vi.fn((callback: FrameRequestCallback) => {
      paint = callback;
      return 7;
    });
    const cancelFrame = vi.fn();
    vi.stubGlobal("requestAnimationFrame", requestFrame);
    vi.stubGlobal("cancelAnimationFrame", cancelFrame);

    liveResponseStore.startRun("run-smooth");
    liveResponseStore.startMessage("message-smooth");
    liveResponseStore.append("message-smooth", "平");
    liveResponseStore.append("message-smooth", "滑");

    expect(requestFrame).toHaveBeenCalledTimes(1);
    expect(liveResponseStore.getSnapshot().text).toBe("");

    paint?.(16);
    expect(liveResponseStore.getSnapshot()).toMatchObject({
      text: "平滑",
      status: "streaming",
    });

    liveResponseStore.append("message-smooth", "完成");
    liveResponseStore.completeMessage("message-smooth");
    expect(liveResponseStore.getSnapshot()).toMatchObject({
      text: "平滑完成",
      status: "complete",
    });

    const notification = vi.fn();
    const unsubscribe = liveResponseStore.subscribe(notification);
    liveResponseStore.completeRun();
    expect(notification).not.toHaveBeenCalled();
    unsubscribe();
  });
});
