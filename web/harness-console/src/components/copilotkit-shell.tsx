"use client";

import { CopilotKit } from "@copilotkit/react-core/v2";
import type { ReactNode } from "react";

export function CopilotKitShell({ children }: { children: ReactNode }) {
  return (
    <CopilotKit
      runtimeUrl="/api/copilotkit"
      useSingleEndpoint={false}
      credentials="same-origin"
      onError={({ type, error, context }) => {
        console.error("[Harness Console]", type, error, context);
      }}
    >
      {children}
    </CopilotKit>
  );
}
