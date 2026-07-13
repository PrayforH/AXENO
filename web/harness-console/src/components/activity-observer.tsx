"use client";

import { useAgent } from "@copilotkit/react-core/v2";
import { useEffect } from "react";
import { latestRunActivity } from "../lib/activity-schema";
import { activityStore } from "../lib/activity-store";

export function ActivityObserver() {
  const { agent } = useAgent({ agentId: "harness-agent", updates: [] });

  useEffect(() => {
    const publish = (messages: readonly unknown[]) => {
      const activity = latestRunActivity(messages);
      if (activity) activityStore.publish(activity);
    };
    publish(agent.messages);
    const subscription = agent.subscribe({
      onMessagesChanged: ({ messages }) => publish(messages),
    });
    return () => subscription.unsubscribe();
  }, [agent]);

  return null;
}
