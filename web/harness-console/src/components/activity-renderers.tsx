"use client";

import type { ReactActivityMessageRenderer } from "@copilotkit/react-core/v2";
import { useEffect } from "react";
import { ActivitySummary } from "./activity-summary";
import { runActivitySchema, type RunActivity } from "../lib/activity-schema";
import { activityStore } from "../lib/activity-store";

function HarnessActivity({ content }: { content: RunActivity }) {
  useEffect(() => {
    activityStore.publish(content);
  }, [content]);
  return <ActivitySummary activity={content} />;
}

const harnessActivityRenderer: ReactActivityMessageRenderer<RunActivity> = {
  activityType: "harness.run.v1",
  agentId: "harness-agent",
  content: runActivitySchema,
  render: ({ content }) => <HarnessActivity content={content} />,
};

export const harnessActivityRenderers = [harnessActivityRenderer];
