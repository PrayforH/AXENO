# public-opinion-agent

`public-opinion-agent@0.3.8` is the Codex edition of the evidence-backed Chinese
public-opinion Agent. Its Studio display name is `涉非舆情分析（Codex）`.

This package was not emitted unchanged by `harness agent init`. It is the worked
reference produced by adapting the earlier `public-opinion` behavior to the Codex loop.
The current version uses workspace evidence and Harness builtins only. It deliberately
does not declare external MCP, `Task`, Python tools or sub-Agents because those features
are outside the current Codex compiler contract.

Version notes:

- `0.3.5`: previous Claude Agent SDK release; keep as the rollback version.
- `0.3.6`: first Codex migration; superseded after its canary exposed stale prompt and
  model-binding issues.
- `0.3.7`: Codex prompt and route correction; superseded so the packaged Skill could be
  aligned with the same runtime boundary.
- `0.3.8`: current Codex release with a Codex-native prompt, Skill, tool boundary and
  model route.

Validate and package:

```bash
uv run harness agent check agents/public-opinion-agent/agent.yaml --environment production
uv run harness agent pack agents/public-opinion-agent/agent.yaml
```

Before running it, bind `public-opinion-agent` to the
`codex-deepseek-v4-flash` route in Studio model management. Existing Sessions stay
pinned to the version and route snapshot created for them; create a new Session after a
version or binding change.
