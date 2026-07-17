export async function register() {
  if (
    process.env.NEXT_RUNTIME === "nodejs" &&
    process.env.HARNESS_OTEL_ENABLED === "true"
  ) {
    await import("./instrumentation-node");
  }
}
