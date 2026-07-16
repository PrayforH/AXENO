export type ServerEnvironment = Readonly<Record<string, string | undefined>>;

export interface HarnessServerConfig {
  apiUrl: string;
  agentName: string;
  agentVersion: string;
  aguiUrl: string;
  identityHeaders: Record<string, string>;
  serviceHeaders: Record<string, string>;
}

export function getHarnessServerConfig(
  environment: ServerEnvironment = process.env,
): HarnessServerConfig {
  const apiUrl = (environment.HARNESS_API_URL ?? "http://127.0.0.1:8000").replace(
    /\/$/,
    "",
  );
  const agentName = environment.HARNESS_AGENT_NAME ?? "echo-agent";
  const agentVersion = environment.HARNESS_AGENT_VERSION ?? "0.4.0";
  const query = new URLSearchParams({
    agent_name: agentName,
    agent_version: agentVersion,
  });

  return {
    apiUrl,
    agentName,
    agentVersion,
    aguiUrl: `${apiUrl}/v1/agui?${query.toString()}`,
    identityHeaders: {
      "X-Tenant-ID": environment.HARNESS_TENANT_ID ?? "local",
      "X-User-ID": environment.HARNESS_USER_ID ?? "developer",
    },
    serviceHeaders: environment.HARNESS_API_BEARER_TOKEN
      ? { Authorization: `Bearer ${environment.HARNESS_API_BEARER_TOKEN}` }
      : {},
  };
}
