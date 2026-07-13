export function developerRows(
  threadId: string,
): ReadonlyArray<readonly [string, string]> {
  return [
    ["THREAD", threadId || "initializing"],
    ["AGENT", "harness-agent"],
    ["ROUTE", "/api/copilotkit → Harness AG-UI"],
  ];
}
