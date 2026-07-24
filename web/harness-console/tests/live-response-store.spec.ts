import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { liveResponseStore } from "../src/lib/live-response-store";

describe("liveResponseStore", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    liveResponseStore.clear();
  });
  afterEach(() => {
    liveResponseStore.clear();
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it("streams a candidate immediately and hides it when a tool follows", () => {
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
      text: "最终回答",
      status: "complete",
      visible: true,
    });

    liveResponseStore.completeRun();
    expect(liveResponseStore.getSnapshot()).toMatchObject({
      runId: "run-1",
      messageId: "final",
      text: "最终回答",
      status: "complete",
      visible: true,
    });
  });

  it("does not publish a pending tool preface as visible during hand-off", () => {
    let paint: FrameRequestCallback | undefined;
    vi.stubGlobal("requestAnimationFrame", (callback: FrameRequestCallback) => {
      paint = callback;
      return 9;
    });
    vi.stubGlobal("cancelAnimationFrame", vi.fn());
    const visibleSnapshots: string[] = [];

    liveResponseStore.startRun("run-preface");
    liveResponseStore.startMessage("message-preface");
    const unsubscribe = liveResponseStore.subscribe(() => {
      const current = liveResponseStore.getSnapshot();
      if (current.visible && current.text) visibleSnapshots.push(current.text);
    });
    liveResponseStore.append("message-preface", "让我换一种方式定位章节。");
    liveResponseStore.hideForTool();
    paint?.(16);

    expect(visibleSnapshots).toEqual([]);
    expect(liveResponseStore.getSnapshot()).toMatchObject({
      text: "让我换一种方式定位章节。",
      visible: false,
    });
    unsubscribe();
  });

  it("publishes a stable candidate on each animation frame", () => {
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
      visible: true,
    });

    liveResponseStore.append("message-smooth", "完成");
    liveResponseStore.completeMessage("message-smooth");
    expect(liveResponseStore.getSnapshot()).toMatchObject({
      text: "平滑完成",
      status: "complete",
      visible: true,
    });

    const notification = vi.fn();
    const unsubscribe = liveResponseStore.subscribe(notification);
    liveResponseStore.completeRun();
    expect(notification).not.toHaveBeenCalled();
    expect(liveResponseStore.getSnapshot()).toMatchObject({
      text: "平滑完成",
      status: "complete",
      visible: true,
    });
    unsubscribe();
  });

  it("streams a substantial active message before the run finishes", () => {
    liveResponseStore.startRun("run-long-answer");
    liveResponseStore.startMessage("answer");
    liveResponseStore.append("answer", "正文".repeat(120));

    expect(liveResponseStore.getSnapshot()).toMatchObject({
      messageId: "answer",
      visible: true,
      status: "streaming",
    });
  });
});
