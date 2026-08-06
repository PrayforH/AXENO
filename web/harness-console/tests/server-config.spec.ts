import { describe, expect, it } from "vitest";
import { getHarnessServerConfig } from "../src/lib/server-config";

describe("Harness server configuration", () => {
  it("uses local defaults without exposing identity in the URL", () => {
    const config = getHarnessServerConfig({});

    expect(config.aguiUrl).toBe(
      "http://127.0.0.1:8000/v1/agui?agent_name=lead-agent&agent_version=1.0.0",
    );
    expect(config.serviceHeaders).toEqual({});
    expect(config.aguiUrl).not.toContain("local");
    expect(config.aguiUrl).not.toContain("developer");
  });

  it("encodes configured agent coordinates", () => {
    const config = getHarnessServerConfig({
      HARNESS_API_URL: "https://harness.internal/",
      HARNESS_AGENT_NAME: "code agent",
      HARNESS_AGENT_VERSION: "2.0+beta",
      HARNESS_API_BEARER_TOKEN: "server-only-token",
    });

    expect(config.aguiUrl).toBe(
      "https://harness.internal/v1/agui?agent_name=code+agent&agent_version=2.0%2Bbeta",
    );
    expect(config.serviceHeaders).toEqual({
      "X-Harness-Service-Token": "server-only-token",
    });
  });
});
