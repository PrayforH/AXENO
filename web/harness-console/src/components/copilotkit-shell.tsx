"use client";

import { CopilotKit } from "@copilotkit/react-core";
import type { ReactNode } from "react";

export function CopilotKitShell({ children }: { children: ReactNode }) {
  const runtimeUrl = process.env.NEXT_PUBLIC_COPILOTKIT_RUNTIME_URL;
  if (!runtimeUrl) return <>{children}</>;
  return <CopilotKit runtimeUrl={runtimeUrl}>{children}</CopilotKit>;
}

