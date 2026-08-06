# public-opinion-agent

Reference production domain Agent for evidence-backed Chinese public-opinion analysis.
It demonstrates that a new domain can reuse the Harness runtime, approval, Sandbox,
Session, sub-Agent, artifact and observability capabilities without forking the Web UI or
agent loop.

This package was not emitted unchanged by `harness agent init`. It is the worked
reference produced by applying the same scaffold contract to the earlier
`public-opinion` domain behavior: the domain prompt, evidence/risk Skill, report
contract, read-only Tavily MCP, helper delegation and deterministic eval fixtures were
reviewed and migrated by hand. New domain Agents should follow this shape after using
`agent init` for their initial skeleton.

Validate and package:

```bash
uv run harness agent check agents/public-opinion-agent/agent.yaml --environment production
uv run harness agent pack agents/public-opinion-agent/agent.yaml
```

The live evaluation suite requires the Agent and `helper-agent@1.0.0` to be published and
the server-owned `tavily-readonly` registration to be configured.
