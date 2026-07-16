export type ServerEnvironment = Readonly<Record<string, string | undefined>>;

export interface HarnessServerConfig {
  apiUrl: string;
  agentName: string;
  agentVersion: string;
  aguiUrl: string;
  serviceHeaders: Record<string, string>;
  cookieSecure: boolean;
  refreshCookieDays: number;
  googleClientId: string;
  githubClientId: string;
  publicUrl: string;
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
    serviceHeaders: environment.HARNESS_API_BEARER_TOKEN
      ? { "X-Harness-Service-Token": environment.HARNESS_API_BEARER_TOKEN }
      : {},
    cookieSecure: environment.AUTH_COOKIE_SECURE === "true",
    refreshCookieDays: Number(environment.AUTH_REFRESH_COOKIE_DAYS ?? "30"),
    googleClientId: environment.AUTH_GOOGLE_CLIENT_ID ?? "",
    githubClientId: environment.AUTH_GITHUB_CLIENT_ID ?? "",
    publicUrl: (environment.AUTH_PUBLIC_URL ?? "").replace(/\/$/, ""),
  };
}
