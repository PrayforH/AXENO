import {
  CopilotRuntime,
  createCopilotRuntimeHandler,
} from "@copilotkit/runtime/v2";
import { getHarnessServerConfig } from "../../../../lib/server-config";
import { HarnessHttpAgent } from "../../../../lib/harness-agent";

const config = getHarnessServerConfig();
const runtime = new CopilotRuntime({
  agents: {
    "harness-agent": new HarnessHttpAgent({
      agentId: "harness-agent",
      url: config.aguiUrl,
      headers: config.identityHeaders,
    }),
  },
});

const handler = createCopilotRuntimeHandler({
  runtime,
  basePath: "/api/copilotkit",
});

export const GET = handler;
export const POST = handler;
export const OPTIONS = handler;
