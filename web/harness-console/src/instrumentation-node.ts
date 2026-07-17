import { registerOTel } from "@vercel/otel";

registerOTel({
  serviceName: "claude-agent-harness-web",
  attributes: {
    "deployment.environment.name":
      process.env.HARNESS_OTEL_ENVIRONMENT || "production",
  },
  instrumentations: [],
});
