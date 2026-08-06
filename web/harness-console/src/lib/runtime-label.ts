export function runtimeDisclaimer(runtime: string | undefined): string {
  if (runtime === "claude-sdk") {
    return "Claude SDK · cc-switch · Langfuse 默认关闭";
  }
  return "本地 Fake Runtime · Langfuse 默认关闭";
}
