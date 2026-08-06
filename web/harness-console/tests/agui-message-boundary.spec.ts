import type { ChatModelRunResult } from "@assistant-ui/core";
import { describe, expect, it, vi } from "vitest";
import { RunAggregator } from "../node_modules/@assistant-ui/react-ag-ui/src/runtime/adapter/run-aggregator";

describe("AG-UI provider text boundaries", () => {
  it("keeps final prose in a text part after operational tools", () => {
    const updates: ChatModelRunResult[] = [];
    const aggregator = new RunAggregator({
      showThinking: true,
      logger: { debug: vi.fn(), error: vi.fn() },
      emit: (update) => updates.push(update),
    });

    const handle = (event: object) => aggregator.handle(event as never);
    handle({ type: "RUN_STARTED", runId: "run-boundaries" });
    // This first ID owns the durable assistant turn.
    handle({ type: "TEXT_MESSAGE_START", messageId: "assistant-run-boundaries" });
    // Provider IDs remain distinct text-part keys around tool boundaries.
    handle({ type: "TEXT_MESSAGE_START", messageId: "provider-progress" });
    handle({
      type: "TEXT_MESSAGE_CONTENT",
      messageId: "provider-progress",
      delta: "继续核验。",
    });
    handle({
      type: "TOOL_CALL_START",
      toolCallId: "search-1",
      toolCallName: "search",
      parentMessageId: "provider-progress",
    });
    handle({ type: "TOOL_CALL_ARGS", toolCallId: "search-1", delta: "{}" });
    handle({ type: "TOOL_CALL_END", toolCallId: "search-1" });
    handle({
      type: "TOOL_CALL_RESULT",
      toolCallId: "search-1",
      messageId: "tool-result-1",
      content: "ok",
      role: "tool",
    });
    handle({ type: "TEXT_MESSAGE_END", messageId: "provider-progress" });
    handle({ type: "TEXT_MESSAGE_START", messageId: "provider-final" });
    handle({
      type: "TEXT_MESSAGE_CONTENT",
      messageId: "provider-final",
      delta: "## 核验结果\n\n完整回答",
    });
    handle({ type: "TEXT_MESSAGE_END", messageId: "provider-final" });
    handle({ type: "TEXT_MESSAGE_END", messageId: "assistant-run-boundaries" });
    handle({ type: "RUN_FINISHED", runId: "run-boundaries" });

    const content = updates.at(-1)?.content ?? [];
    expect(content.map((part) => part.type)).toEqual([
      "text",
      "text",
      "tool-call",
      "text",
    ]);
    expect(
      content.filter((part) => part.type === "text").map((part) => part.text),
    ).toEqual(["", "继续核验。", "## 核验结果\n\n完整回答"]);
  });
});
