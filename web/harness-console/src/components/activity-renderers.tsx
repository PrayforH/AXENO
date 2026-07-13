import type { ReactActivityMessageRenderer } from "@copilotkit/react-core/v2";
import { ActivitySummary } from "./activity-summary";
import { runActivitySchema, type RunActivity } from "../lib/activity-schema";

const harnessActivityRenderer: ReactActivityMessageRenderer<RunActivity> = {
  activityType: "harness.run.v1",
  agentId: "harness-agent",
  content: runActivitySchema,
  render: ({ content }) => <ActivitySummary activity={content} />,
};

export const harnessActivityRenderers = [harnessActivityRenderer];
